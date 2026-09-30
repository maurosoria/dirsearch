//! Proxy client construction, rotation, and retry policy.

use reqwest::{Client, ClientBuilder, Proxy};
use std::sync::Arc;

/// Reqwest clients arranged by proxy and, when required, by scan worker.
///
/// Most authentication can share one pooled client per proxy. Connection-bound
/// authentication instead creates one client per worker and proxy so every
/// challenge exchange remains on the worker's HTTP/1.1 connection.
pub(crate) struct ProxyClientPool {
    clients: Arc<Vec<Client>>,
    clients_per_proxy: usize,
}

impl ProxyClientPool {
    pub(crate) fn build<F>(
        proxy_urls: &[String],
        clients_per_proxy: usize,
        mut build_client: F,
    ) -> Result<Self, String>
    where
        F: FnMut(Option<&str>) -> Result<Client, String>,
    {
        let clients_per_proxy = clients_per_proxy.max(1);
        let proxy_count = proxy_urls.len().max(1);
        let mut clients = Vec::with_capacity(proxy_count * clients_per_proxy);

        if proxy_urls.is_empty() {
            for _ in 0..clients_per_proxy {
                clients.push(build_client(None)?);
            }
        } else {
            for proxy_url in proxy_urls {
                for _ in 0..clients_per_proxy {
                    clients.push(build_client(Some(proxy_url))?);
                }
            }
        }

        Ok(Self {
            clients: Arc::new(clients),
            clients_per_proxy,
        })
    }

    /// Select a proxy in round-robin request order and preserve worker
    /// affinity inside that proxy's client group.
    pub(crate) fn client_for(&self, request_index: usize, worker_index: usize) -> &Client {
        &self.clients[self.client_index(request_index, worker_index)]
    }

    fn client_index(&self, request_index: usize, worker_index: usize) -> usize {
        if self.clients_per_proxy == 1 {
            request_index % self.clients.len()
        } else {
            let proxy_count = self.clients.len() / self.clients_per_proxy;
            let proxy_index = request_index % proxy_count;
            debug_assert!(worker_index < self.clients_per_proxy);
            proxy_index * self.clients_per_proxy + worker_index
        }
    }
}

pub(crate) fn configure_client(
    builder: ClientBuilder,
    proxy_url: Option<&str>,
) -> Result<ClientBuilder, String> {
    match proxy_url {
        Some(proxy_url) => {
            Ok(builder.proxy(Proxy::all(proxy_url).map_err(|error| error.to_string())?))
        }
        None => Ok(builder),
    }
}

pub(crate) fn is_non_retryable_error(error: &str) -> bool {
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

#[cfg(test)]
mod tests {
    use super::ProxyClientPool;

    #[test]
    fn direct_pool_preserves_worker_affinity() {
        let pool = ProxyClientPool::build(&[], 3, |_| Ok(reqwest::Client::new())).unwrap();

        assert_eq!(pool.client_index(0, 0), 0);
        assert_eq!(pool.client_index(1, 1), 1);
        assert_eq!(pool.client_index(2, 2), 2);
        assert_eq!(pool.client_index(3, 0), 0);
    }

    #[test]
    fn proxied_pool_rotates_proxies_and_preserves_worker_affinity() {
        let proxies = vec![
            "http://proxy-one.invalid".to_string(),
            "http://proxy-two.invalid".to_string(),
        ];
        let mut built_for = Vec::new();
        let pool = ProxyClientPool::build(&proxies, 2, |proxy_url| {
            built_for.push(proxy_url.unwrap().to_string());
            Ok(reqwest::Client::new())
        })
        .unwrap();

        assert_eq!(
            built_for,
            vec![
                proxies[0].clone(),
                proxies[0].clone(),
                proxies[1].clone(),
                proxies[1].clone(),
            ]
        );
        assert_eq!(pool.client_index(0, 0), 0);
        assert_eq!(pool.client_index(1, 0), 2);
        assert_eq!(pool.client_index(2, 1), 1);
        assert_eq!(pool.client_index(3, 1), 3);
    }
}
