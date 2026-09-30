//! Reqwest client construction and request execution.

use crate::compression::{decode_async, decode_error, AsyncBodyReader};
use crate::filters::NativeFilterConfig;
use crate::ntlm::{tls_server_end_point, NtlmExchange};
use crate::raw_http;
use crate::result::{
    native_error_result, native_filtered_marker, native_http_result_with_length, NativeHttpResult,
};
use crate::routing::ConnectionRoutes;
use crate::session::{with_initial_cookie_override, NativeCookieStore};
use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use bytes::Bytes;
use digest_auth::{AuthContext, HttpMethod};
use futures_util::TryStreamExt;
use reqwest::header::{
    HeaderMap, HeaderValue, AUTHORIZATION, CONNECTION, CONTENT_ENCODING, USER_AGENT,
    WWW_AUTHENTICATE,
};
use reqwest::Method;
use std::cell::RefCell;
use std::collections::{hash_map::RandomState, HashMap};
use std::hash::{BuildHasher, Hasher};
use std::io;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::AsyncReadExt;
use tokio_util::io::StreamReader;

pub(crate) type HeaderPairs = Vec<(String, String)>;
/// Immutable User-Agent corpus with one lock-free selection sequence.
///
/// The values belong to the engine context. Only the sequence changes, so
/// workers never mutate the shared header map or contend on a mutex.
#[derive(Clone)]
pub(crate) struct RandomUserAgentPool {
    values: Arc<[RandomUserAgent]>,
    seed: u64,
    sequence: Arc<AtomicU64>,
}

struct RandomUserAgent {
    raw: String,
    header: HeaderValue,
}

impl RandomUserAgentPool {
    pub(crate) fn from_values(values: Vec<String>) -> Result<Option<Self>, String> {
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_usize(values.len());
        Self::from_values_with_seed(values, hasher.finish())
    }

    fn from_values_with_seed(values: Vec<String>, seed: u64) -> Result<Option<Self>, String> {
        if values.is_empty() {
            return Ok(None);
        }
        let values = values
            .into_iter()
            .map(|raw| {
                let header = HeaderValue::try_from(raw.as_str())
                    .map_err(|error| format!("Invalid random User-Agent value: {error}"))?;
                Ok(RandomUserAgent { raw, header })
            })
            .collect::<Result<Vec<_>, String>>()?;
        Ok(Some(Self {
            values: values.into(),
            seed,
            sequence: Arc::new(AtomicU64::new(0)),
        }))
    }

    fn select(&self) -> &RandomUserAgent {
        // This counter supplies distinct PRNG input; it does not synchronize
        // data, so relaxed ordering is sufficient across request workers.
        let sequence = self.sequence.fetch_add(1, Ordering::Relaxed);
        let random = splitmix64(self.seed.wrapping_add(sequence));
        &self.values[(random as usize) % self.values.len()]
    }

    pub(crate) fn select_raw(&self) -> &str {
        &self.select().raw
    }

    fn select_header(&self) -> &HeaderValue {
        &self.select().header
    }

    #[cfg(test)]
    pub(crate) fn seeded(values: Vec<String>, seed: u64) -> Result<Option<Self>, String> {
        Self::from_values_with_seed(values, seed)
    }

    #[cfg(test)]
    pub(crate) fn select_text(&self) -> &str {
        self.select_raw()
    }
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    value ^ (value >> 31)
}

#[derive(Clone)]
pub(crate) enum OriginAuth {
    None,
    Basic {
        username: String,
        password: String,
    },
    Bearer(String),
    Digest {
        username: String,
        password: String,
        challenges: Arc<Mutex<HashMap<String, digest_auth::WwwAuthenticateHeader>>>,
    },
    Ntlm {
        username: String,
        password: String,
    },
}

impl OriginAuth {
    pub(crate) fn from_config(auth_type: &str, credential: &str) -> Result<Self, String> {
        if auth_type.is_empty() && credential.is_empty() {
            return Ok(Self::None);
        }
        if auth_type.is_empty() || credential.is_empty() {
            return Err("Authentication type and credential must be provided together".to_string());
        }

        let split_credential = || credential.split_once(':').unwrap_or((credential, ""));
        match auth_type.to_ascii_lowercase().as_str() {
            "basic" => {
                let (username, password) = split_credential();
                Ok(Self::Basic {
                    username: username.to_string(),
                    password: password.to_string(),
                })
            }
            "bearer" | "jwt" => Ok(Self::Bearer(credential.to_string())),
            "digest" => {
                let (username, password) = split_credential();
                Ok(Self::Digest {
                    username: username.to_string(),
                    password: password.to_string(),
                    challenges: Arc::new(Mutex::new(HashMap::new())),
                })
            }
            "ntlm" => {
                let (username, password) = split_credential();
                Ok(Self::Ntlm {
                    username: username.to_string(),
                    password: password.to_string(),
                })
            }
            other => Err(format!("Unsupported native authentication type: {other}")),
        }
    }

    pub(crate) fn preemptive_authorization(&self) -> Option<String> {
        match self {
            Self::Basic { username, password } => Some(format!(
                "Basic {}",
                BASE64_STANDARD.encode(format!("{username}:{password}"))
            )),
            Self::Bearer(token) => Some(format!("Bearer {token}")),
            Self::None | Self::Digest { .. } | Self::Ntlm { .. } => None,
        }
    }

    pub(crate) fn requires_challenge(&self) -> bool {
        matches!(self, Self::Digest { .. } | Self::Ntlm { .. })
    }

    pub(crate) fn is_connection_bound(&self) -> bool {
        matches!(self, Self::Ntlm { .. })
    }

    pub(crate) fn challenge_name(&self) -> &'static str {
        match self {
            Self::Digest { .. } => "Digest",
            Self::Ntlm { .. } => "NTLM",
            _ => "challenge-response",
        }
    }
}

tokio::task_local! {
    static REDIRECT_HISTORY: RefCell<Vec<String>>;
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn build_http_client(
    headers: &HeaderMap,
    concurrency: usize,
    timeout_secs: f64,
    follow_redirects: bool,
    max_redirects: usize,
    proxy_url: Option<&str>,
    client_identity: Option<(&[u8], &[u8])>,
    cookie_store: Arc<NativeCookieStore>,
    connection_routes: &ConnectionRoutes,
    network_interface: &str,
    connection_bound_auth: bool,
) -> Result<reqwest::Client, String> {
    let has_client_identity = client_identity.is_some();
    let mut builder = reqwest::Client::builder()
        .danger_accept_invalid_certs(true)
        .default_headers(headers.clone())
        .redirect(if follow_redirects {
            let limited = reqwest::redirect::Policy::limited(max_redirects);
            reqwest::redirect::Policy::custom(move |attempt| {
                // Reqwest clones its redirect state per request. Mirror that
                // isolation here so concurrent scans cannot mix URL chains.
                let _ = REDIRECT_HISTORY.try_with(|history| {
                    // The callback runs once per hop. Only append the URL that
                    // produced this redirect instead of rebuilding the chain.
                    if let Some(previous_url) = attempt.previous().last() {
                        history.borrow_mut().push(previous_url.to_string());
                    }
                });
                limited.redirect(attempt)
            })
        } else {
            reqwest::redirect::Policy::none()
        })
        .timeout(Duration::from_secs_f64(timeout_secs))
        .pool_max_idle_per_host(if connection_bound_auth {
            1
        } else {
            concurrency
        })
        .cookie_provider(cookie_store);

    if connection_bound_auth {
        // NTLM authenticates an HTTP/1.1 connection, not an individual
        // request. A client is dedicated to each worker, and this one-entry
        // pool keeps the Type 1/2/3 exchange on that worker's socket.
        builder = builder.http1_only().tls_info(true);
    }

    builder = connection_routes.configure_client(builder, network_interface)?;

    if let Some((client_certificate, client_key)) = client_identity {
        let mut identity_pem = Vec::with_capacity(client_certificate.len() + client_key.len() + 1);
        identity_pem.extend_from_slice(client_certificate);
        if !client_certificate.ends_with(b"\n") {
            identity_pem.push(b'\n');
        }
        identity_pem.extend_from_slice(client_key);
        let identity = reqwest::Identity::from_pem(&identity_pem)
            .map_err(|error| format!("Invalid client certificate or private key: {error}"))?;
        builder = builder.identity(identity);
    }

    if let Some(proxy_url) = proxy_url {
        builder = builder.proxy(reqwest::Proxy::all(proxy_url).map_err(|error| error.to_string())?);
    }

    builder.build().map_err(|error| {
        if has_client_identity {
            format!(
                "Invalid client certificate or private key: {}",
                format_error_chain(&error)
            )
        } else {
            error.to_string()
        }
    })
}

/// Borrowed inputs and output policy for one logical reqwest request.
///
/// This value exists only while one target (including its retries) is being
/// processed. Engine-lifetime resources stay in `NativeRequestContext`, and
/// scan scheduling stays in `ScanTask`; keeping this request borrowed avoids
/// cloning those owners for each URL.
pub(crate) struct ClientRequest<'a> {
    pub(crate) client: &'a reqwest::Client,
    pub(crate) url: &'a str,
    pub(crate) method: &'a Method,
    pub(crate) body: &'a Bytes,
    /// Overrides the shared jar only for the first hop of each retry attempt.
    pub(crate) initial_cookie_override: Option<HeaderValue>,
    /// Enables task-local redirect collection for this request only.
    pub(crate) capture_redirect_history: bool,
    pub(crate) max_retries: usize,
    pub(crate) max_body_size: usize,
    pub(crate) start: Instant,
    pub(crate) filter_config: &'a NativeFilterConfig,
    /// Avoid retaining a response body when its status alone excludes it.
    pub(crate) skip_status_filtered_body: bool,
    pub(crate) origin_auth: &'a OriginAuth,
    /// Selected independently for every network attempt and then kept stable
    /// across redirects or a Digest challenge within that attempt.
    pub(crate) random_user_agents: Option<&'a RandomUserAgentPool>,
}

pub(crate) async fn request_with_client(request: ClientRequest<'_>) -> NativeHttpResult {
    let mut last_error = None;
    let mut attempt_start = request.start;
    for attempt in 0..=request.max_retries {
        match request_once(&request, attempt_start).await {
            Ok(result) => return result,
            Err(error) => {
                let retryable = !is_non_retryable_proxy_error(&error);
                last_error = Some(error);
                if !retryable || attempt == request.max_retries {
                    break;
                }
                // Python requesters report elapsed time for the final attempt,
                // rather than accumulating time spent in earlier failures.
                attempt_start = Instant::now();
            }
        }
    }

    native_error_result(
        String::new(),
        attempt_start.elapsed().as_secs_f64() * 1000.0,
        last_error.unwrap_or_else(|| "request failed".to_string()),
    )
}

pub(crate) fn is_non_retryable_proxy_error(error: &str) -> bool {
    let error = error.to_ascii_lowercase();
    [
        "tunnel error: unsuccessful",
        "proxy authentication required",
        "proxy authorization required",
        "socks error: credentials not accepted",
    ]
    .iter()
    .any(|marker| error.contains(marker))
}

async fn request_once(
    request: &ClientRequest<'_>,
    start: Instant,
) -> Result<NativeHttpResult, String> {
    let random_user_agent = request
        .random_user_agents
        .map(RandomUserAgentPool::select_header);
    let send_request = || send_authenticated_request(request, random_user_agent);
    let (response, redirect_history) = if request.capture_redirect_history {
        REDIRECT_HISTORY
            .scope(RefCell::new(Vec::new()), async {
                let result = send_request().await;
                let history = REDIRECT_HISTORY.with(|history| history.borrow().clone());
                (result, history)
            })
            .await
    } else {
        (send_request().await, Vec::new())
    };
    let response = response?;
    let status = response.status().as_u16();
    let final_url = response.url().to_string();
    if request.skip_status_filtered_body
        && status != 407
        && request.filter_config.status_filter_reason(status).is_some()
    {
        let encodings = response_encodings(response.headers());
        read_decoded_body(response, encodings, 0, false).await?;
        let mut result = native_filtered_marker(status, start.elapsed().as_secs_f64() * 1000.0);
        result.history = redirect_history;
        result.final_url = final_url;
        return Ok(result);
    }
    let headers = response
        .headers()
        .iter()
        .map(|(name, value)| {
            (
                name.as_str().to_string(),
                value.to_str().unwrap_or_default().to_string(),
            )
        })
        .collect::<Vec<_>>();
    let (body, body_length) = read_response_body(response, &headers, request.max_body_size).await?;
    let mut result = native_http_result_with_length(
        String::new(),
        status,
        headers,
        body,
        body_length,
        start.elapsed().as_secs_f64() * 1000.0,
        request.filter_config,
    );
    result.history = redirect_history;
    result.final_url = final_url;
    Ok(result)
}

async fn send_authenticated_request(
    request: &ClientRequest<'_>,
    random_user_agent: Option<&HeaderValue>,
) -> Result<reqwest::Response, String> {
    let build_request = |target: &str| {
        let mut builder = request.client.request(request.method.clone(), target);
        if let Some(user_agent) = random_user_agent {
            builder = builder.header(USER_AGENT, user_agent.clone());
        }
        if request.body.is_empty() {
            builder
        } else {
            builder.body((*request.body).clone())
        }
    };

    match request.origin_auth {
        OriginAuth::None => send_with_cookie_override(request, build_request(request.url)).await,
        OriginAuth::Basic { .. } | OriginAuth::Bearer(_) => {
            let builder = build_request(request.url).header(
                AUTHORIZATION,
                request.origin_auth.preemptive_authorization().unwrap(),
            );
            send_with_cookie_override(request, builder).await
        }
        OriginAuth::Digest {
            username,
            password,
            challenges,
        } => {
            let original_url = reqwest::Url::parse(request.url)
                .map_err(|error| format!("Invalid authentication target URL: {error}"))?;
            let preemptive = digest_authorization(
                &original_url,
                request.method,
                request.body,
                username,
                password,
                challenges,
                None,
            )?;
            let mut builder = build_request(request.url);
            if let Some(authorization) = preemptive {
                builder = builder.header(AUTHORIZATION, authorization);
            }
            let response = send_with_cookie_override(request, builder).await?;
            if response.status() != reqwest::StatusCode::UNAUTHORIZED {
                return Ok(response);
            }

            let Some(challenge) = digest_challenge(response.headers())? else {
                return Ok(response);
            };
            if !same_origin(&original_url, response.url()) {
                // A redirect must never widen the credential scope.
                return Ok(response);
            }

            let challenge_url = response.url().clone();
            let answer = digest_authorization(
                &challenge_url,
                request.method,
                request.body,
                username,
                password,
                challenges,
                Some(&challenge),
            )?
            .expect("a parsed Digest challenge must produce an authorization value");
            drop(response);

            let builder = build_request(challenge_url.as_str()).header(AUTHORIZATION, answer);
            send_with_cookie_override(request, builder).await
        }
        OriginAuth::Ntlm { username, password } => {
            send_ntlm_authenticated_request(request, &build_request, username, password).await
        }
    }
}

async fn send_ntlm_authenticated_request<F>(
    request: &ClientRequest<'_>,
    build_request: &F,
    username: &str,
    password: &str,
) -> Result<reqwest::Response, String>
where
    F: Fn(&str) -> reqwest::RequestBuilder,
{
    let original_url = reqwest::Url::parse(request.url)
        .map_err(|error| format!("Invalid NTLM authentication target URL: {error}"))?;
    let response = send_with_cookie_override(
        request,
        build_request(request.url).header(CONNECTION, "Keep-Alive"),
    )
    .await?;
    if response.status() != reqwest::StatusCode::UNAUTHORIZED {
        return Ok(response);
    }

    let Some(auth_scheme) = ntlm_authentication_scheme(response.headers())? else {
        return Ok(response);
    };
    if !same_origin(&original_url, response.url()) {
        // A redirect must never widen the credential scope.
        return Ok(response);
    }
    let challenge_url = response.url().clone();
    let target_host = challenge_url
        .host_str()
        .ok_or_else(|| "NTLM authentication target has no host".to_string())?;
    let channel_bindings = ntlm_channel_bindings(&challenge_url, &response)?;
    drain_authentication_response(response).await?;

    let mut exchange = NtlmExchange::new(username, password, target_host)?;
    let negotiate = BASE64_STANDARD.encode(exchange.negotiate_token()?);
    let response = send_with_cookie_override(
        request,
        build_request(challenge_url.as_str())
            .header(CONNECTION, "Keep-Alive")
            .header(AUTHORIZATION, format!("{auth_scheme} {negotiate}")),
    )
    .await?;
    if response.status() != reqwest::StatusCode::UNAUTHORIZED {
        return Err(
            "NTLM server accepted a negotiate token without proving credentials".to_string(),
        );
    }
    if !same_origin(&challenge_url, response.url()) {
        return Err("NTLM challenge was redirected to a different origin".to_string());
    }
    let challenge = ntlm_challenge(response.headers(), auth_scheme)?;
    let challenge_url = response.url().clone();
    drain_authentication_response(response).await?;

    let authenticate = BASE64_STANDARD
        .encode(exchange.authenticate_token(challenge, channel_bindings.as_deref())?);
    send_with_cookie_override(
        request,
        build_request(challenge_url.as_str())
            .header(CONNECTION, "Keep-Alive")
            .header(AUTHORIZATION, format!("{auth_scheme} {authenticate}")),
    )
    .await
}

pub(crate) fn ntlm_authentication_scheme(
    headers: &HeaderMap,
) -> Result<Option<&'static str>, String> {
    let mut negotiate = false;
    for value in headers.get_all(WWW_AUTHENTICATE) {
        let value = value
            .to_str()
            .map_err(|_| "NTLM authentication challenge is not valid text".to_string())?;
        for challenge in value.split(',').map(str::trim) {
            let scheme = challenge
                .split_ascii_whitespace()
                .next()
                .unwrap_or_default();
            if scheme.eq_ignore_ascii_case("ntlm") {
                return Ok(Some("NTLM"));
            }
            negotiate |= scheme.eq_ignore_ascii_case("negotiate");
        }
    }
    Ok(negotiate.then_some("Negotiate"))
}

pub(crate) fn ntlm_challenge(headers: &HeaderMap, auth_scheme: &str) -> Result<Vec<u8>, String> {
    for value in headers.get_all(WWW_AUTHENTICATE) {
        let value = value
            .to_str()
            .map_err(|_| "NTLM authentication challenge is not valid text".to_string())?;
        for challenge in value.split(',').map(str::trim) {
            let mut parts = challenge.split_ascii_whitespace();
            if parts
                .next()
                .is_some_and(|scheme| scheme.eq_ignore_ascii_case(auth_scheme))
            {
                let encoded = parts
                    .next()
                    .ok_or_else(|| "NTLM server did not return a challenge token".to_string())?;
                return BASE64_STANDARD
                    .decode(encoded)
                    .map_err(|_| "NTLM server returned an invalid challenge token".to_string());
            }
        }
    }
    Err("NTLM server did not return a challenge token".to_string())
}

fn ntlm_channel_bindings(
    url: &reqwest::Url,
    response: &reqwest::Response,
) -> Result<Option<Vec<u8>>, String> {
    if url.scheme() != "https" {
        return Ok(None);
    }
    let certificate = response
        .extensions()
        .get::<reqwest::tls::TlsInfo>()
        .and_then(reqwest::tls::TlsInfo::peer_certificate)
        .ok_or_else(|| {
            "HTTPS NTLM authentication could not read the TLS certificate for CBT".to_string()
        })?;
    tls_server_end_point(certificate).map(Some)
}

async fn drain_authentication_response(response: reqwest::Response) -> Result<(), String> {
    let encodings = response_encodings(response.headers());
    read_decoded_body(response, encodings, 0, false)
        .await
        .map(|_| ())
}

async fn send_with_cookie_override(
    request: &ClientRequest<'_>,
    builder: reqwest::RequestBuilder,
) -> Result<reqwest::Response, String> {
    // A Digest challenge response starts a new top-level send. Re-arm the
    // configured Cookie value for that send while letting redirect hops use
    // the shared session jar after the first cookie-provider lookup.
    with_initial_cookie_override(request.initial_cookie_override.clone(), async {
        builder
            .send()
            .await
            .map_err(|error| format_error_chain(&error))
    })
    .await
}

#[allow(clippy::too_many_arguments)]
fn digest_authorization(
    url: &reqwest::Url,
    method: &Method,
    body: &Bytes,
    username: &str,
    password: &str,
    challenges: &Mutex<HashMap<String, digest_auth::WwwAuthenticateHeader>>,
    new_challenge: Option<&str>,
) -> Result<Option<String>, String> {
    let origin = url.origin().ascii_serialization();
    let mut challenges = challenges
        .lock()
        .map_err(|_| "Digest authentication challenge cache is unavailable".to_string())?;
    if let Some(challenge) = new_challenge {
        let prompt = digest_auth::parse(challenge)
            .map_err(|error| format!("Invalid Digest authentication challenge: {error}"))?;
        challenges.insert(origin.clone(), prompt);
    }
    let Some(prompt) = challenges.get_mut(&origin) else {
        return Ok(None);
    };

    let mut digest_uri = url.path().to_string();
    if let Some(query) = url.query() {
        digest_uri.push('?');
        digest_uri.push_str(query);
    }
    let body = (!body.is_empty()).then_some(body.as_ref());
    let context = AuthContext::new_with_method(
        username,
        password,
        &digest_uri,
        body,
        HttpMethod::from(method.as_str()),
    );
    // The shared prompt also serializes nonce-count increments. The lock is
    // released before any network I/O, so concurrent requests only contend for
    // the small hash computation rather than for the request itself.
    prompt
        .respond(&context)
        .map(|answer| Some(answer.to_string()))
        .map_err(|error| format!("Could not answer Digest authentication challenge: {error}"))
}

fn digest_challenge(headers: &HeaderMap) -> Result<Option<String>, String> {
    for value in headers.get_all(WWW_AUTHENTICATE) {
        let value = value
            .to_str()
            .map_err(|_| "Digest authentication challenge is not valid text".to_string())?;
        let lowercase = value.to_ascii_lowercase();
        if lowercase.starts_with("digest ") {
            return Ok(Some(value.to_string()));
        }
        if let Some(index) = lowercase.find(", digest ") {
            return Ok(Some(value[index + 2..].to_string()));
        }
    }
    Ok(None)
}

fn same_origin(left: &reqwest::Url, right: &reqwest::Url) -> bool {
    left.scheme() == right.scheme()
        && left.host_str() == right.host_str()
        && left.port_or_known_default() == right.port_or_known_default()
}

fn format_error_chain(error: &dyn std::error::Error) -> String {
    let mut message = error.to_string();
    let mut source = error.source();
    while let Some(error) = source {
        message.push_str(": ");
        message.push_str(&error.to_string());
        source = error.source();
    }
    message
}

pub(crate) async fn read_response_body(
    response: reqwest::Response,
    headers: &HeaderPairs,
    max_body_size: usize,
) -> Result<(Vec<u8>, usize), String> {
    let encodings = raw_http::comma_separated_header_values(headers, "content-encoding");
    read_decoded_body(response, encodings, max_body_size, true).await
}

fn response_encodings(headers: &HeaderMap) -> Vec<String> {
    headers
        .get_all(CONTENT_ENCODING)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .flat_map(|value| value.split(','))
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .collect()
}

async fn read_decoded_body(
    response: reqwest::Response,
    encodings: Vec<String>,
    max_body_size: usize,
    capture_body: bool,
) -> Result<(Vec<u8>, usize), String> {
    let capacity = if capture_body {
        response
            .content_length()
            .and_then(|length| usize::try_from(length).ok())
            .unwrap_or_default()
            .min(max_body_size)
    } else {
        0
    };
    let stream = response.bytes_stream().map_err(io::Error::other);
    let reader: AsyncBodyReader = Box::pin(StreamReader::new(stream));
    let mut reader = decode_async(reader, &encodings)?;
    let mut body = Vec::with_capacity(capacity);
    let mut body_length = 0usize;
    let mut buffer = [0u8; 8192];

    loop {
        let read = reader
            .read(&mut buffer)
            .await
            .map_err(|error| decode_error(&encodings, error))?;
        if read == 0 {
            break;
        }
        body_length = body_length.saturating_add(read);
        if capture_body {
            append_body_chunk(&mut body, &buffer[..read], max_body_size);
        }
    }

    Ok((body, body_length))
}

pub(crate) fn append_body_chunk(body: &mut Vec<u8>, chunk: &[u8], max_body_size: usize) {
    let remaining = max_body_size.saturating_sub(body.len());
    body.extend_from_slice(&chunk[..chunk.len().min(remaining)]);
}
