//! Connection routing shared by reqwest and the byte-preserving HTTP client.

use reqwest::ClientBuilder;
use std::collections::HashMap;
use std::net::{IpAddr, SocketAddr};
use std::time::Instant;
use tokio::net::{lookup_host, TcpSocket, TcpStream};

pub(crate) type ConnectionOverrideConfig = Vec<(String, u16, String)>;

#[derive(Debug, Default)]
pub(crate) struct ConnectionRoutes {
    by_origin: HashMap<(String, u16), IpAddr>,
    by_host: Vec<(String, SocketAddr)>,
}

impl ConnectionRoutes {
    pub(crate) fn from_config(config: &ConnectionOverrideConfig) -> Result<Self, String> {
        let mut by_origin = HashMap::with_capacity(config.len());
        let mut resolver_ips = HashMap::with_capacity(config.len());

        for (host, port, configured_ip) in config {
            let host = normalize_host(host);
            if host.is_empty() {
                return Err("Native connection override host must not be empty".to_string());
            }
            let ip_text = configured_ip
                .strip_prefix('[')
                .and_then(|value| value.strip_suffix(']'))
                .unwrap_or(configured_ip);
            let ip = ip_text.parse::<IpAddr>().map_err(|error| {
                format!("Invalid --ip value {configured_ip:?} for {host}:{port}: {error}")
            })?;
            if let Ok(origin_ip) = host.parse::<IpAddr>() {
                if origin_ip != ip {
                    return Err(
                        "The native backend cannot reroute an IP-literal target with --ip; use a hostname or the Python backend"
                            .to_string(),
                    );
                }
            }

            by_origin.insert((host.clone(), *port), ip);
            if let Some(previous_ip) = resolver_ips.insert(host.clone(), ip) {
                if previous_ip != ip {
                    return Err(format!(
                        "Native --ip overrides for {host} must use the same address on every port"
                    ));
                }
            }
        }

        let mut by_host = resolver_ips
            .into_iter()
            .map(|(host, ip)| (host, SocketAddr::new(ip, 0)))
            .collect::<Vec<_>>();
        by_host.sort_by(|left, right| left.0.cmp(&right.0));

        Ok(Self { by_origin, by_host })
    }

    pub(crate) fn configure_client(
        &self,
        mut builder: ClientBuilder,
        network_interface: &str,
    ) -> Result<ClientBuilder, String> {
        for (host, address) in &self.by_host {
            // Reqwest replaces this placeholder port with the URL's port.
            builder = builder.resolve(host, *address);
            // A trailing DNS root label is significant to reqwest's resolver
            // key even though it identifies the same origin for --ip.
            if host.parse::<IpAddr>().is_err() {
                builder = builder.resolve(&format!("{host}."), *address);
            }
        }
        configure_client_interface(builder, network_interface)
    }

    pub(crate) async fn connect_raw(
        &self,
        host: &str,
        port: u16,
        network_interface: &str,
        deadline: Instant,
    ) -> Result<TcpStream, String> {
        let normalized_host = normalize_host(host);
        let addresses = if let Some(ip) = self.by_origin.get(&(normalized_host, port)) {
            vec![SocketAddr::new(*ip, port)]
        } else {
            tokio::time::timeout_at(
                tokio::time::Instant::from_std(deadline),
                lookup_host((host, port)),
            )
            .await
            .map_err(|_| "Raw HTTP name resolution timed out".to_string())?
            .map_err(|error| error.to_string())?
            .collect()
        };

        let mut last_error = None;
        for address in addresses {
            let socket = match address {
                SocketAddr::V4(_) => TcpSocket::new_v4(),
                SocketAddr::V6(_) => TcpSocket::new_v6(),
            }
            .map_err(|error| error.to_string())?;
            bind_socket_to_interface(&socket, network_interface)?;
            match tokio::time::timeout_at(
                tokio::time::Instant::from_std(deadline),
                socket.connect(address),
            )
            .await
            {
                Ok(Ok(stream)) => return Ok(stream),
                Ok(Err(error)) => last_error = Some(error.to_string()),
                Err(_) => return Err("Raw HTTP connection timed out".to_string()),
            }
        }

        Err(last_error.unwrap_or_else(|| "Raw HTTP name resolution returned no addresses".into()))
    }

    #[cfg(test)]
    pub(crate) fn override_for(&self, host: &str, port: u16) -> Option<IpAddr> {
        self.by_origin.get(&(normalize_host(host), port)).copied()
    }
}

fn normalize_host(host: &str) -> String {
    let host = host.trim();
    let host = host
        .strip_prefix('[')
        .and_then(|value| value.strip_suffix(']'))
        .unwrap_or(host);
    let host = host.trim_end_matches('.');
    if host.parse::<IpAddr>().is_ok() {
        return host.to_ascii_lowercase();
    }

    reqwest::Url::parse(&format!("http://{host}/"))
        .ok()
        .and_then(|url| url.host_str().map(str::to_string))
        .unwrap_or_else(|| host.to_ascii_lowercase())
}

#[cfg(any(
    target_os = "android",
    target_os = "fuchsia",
    target_os = "illumos",
    target_os = "ios",
    target_os = "linux",
    target_os = "macos",
    target_os = "solaris",
    target_os = "tvos",
    target_os = "visionos",
    target_os = "watchos",
))]
fn configure_client_interface(
    builder: ClientBuilder,
    network_interface: &str,
) -> Result<ClientBuilder, String> {
    Ok(if network_interface.is_empty() {
        builder
    } else {
        builder.interface(network_interface)
    })
}

#[cfg(not(any(
    target_os = "android",
    target_os = "fuchsia",
    target_os = "illumos",
    target_os = "ios",
    target_os = "linux",
    target_os = "macos",
    target_os = "solaris",
    target_os = "tvos",
    target_os = "visionos",
    target_os = "watchos",
)))]
fn configure_client_interface(
    builder: ClientBuilder,
    network_interface: &str,
) -> Result<ClientBuilder, String> {
    if network_interface.is_empty() {
        Ok(builder)
    } else {
        Err("--interface is not supported by the native backend on this platform".to_string())
    }
}

#[cfg(any(target_os = "android", target_os = "fuchsia", target_os = "linux"))]
fn bind_socket_to_interface(socket: &TcpSocket, network_interface: &str) -> Result<(), String> {
    if network_interface.is_empty() {
        return Ok(());
    }
    socket
        .bind_device(Some(network_interface.as_bytes()))
        .map_err(|error| format!("Could not bind to interface {network_interface:?}: {error}"))
}

#[cfg(not(any(target_os = "android", target_os = "fuchsia", target_os = "linux")))]
fn bind_socket_to_interface(_socket: &TcpSocket, network_interface: &str) -> Result<(), String> {
    if network_interface.is_empty() {
        Ok(())
    } else {
        Err(
            "--interface is not supported by the native raw HTTP transport on this platform"
                .to_string(),
        )
    }
}
