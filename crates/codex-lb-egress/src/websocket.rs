use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;

use base64::Engine as _;
use codex_lb_protocol::{NativeEvent, NativeWebSocketRequest};
use codex_lb_responses::stream::interpret_websocket;
use futures_util::{SinkExt, StreamExt};
use rustls::{ClientConfig, RootCertStore};
use tokio::io::{AsyncRead, AsyncWrite};
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_rustls::TlsConnector;
use tokio_tungstenite::Connector;
use tokio_tungstenite::client_async_tls_with_config;
use tokio_tungstenite::proxy::connect_via_proxy;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::error::TlsError;
use tokio_tungstenite::tungstenite::handshake::client::Response as WebSocketResponse;
use tokio_tungstenite::tungstenite::http::HeaderName as WebSocketHeaderName;
use tokio_tungstenite::tungstenite::http::HeaderValue as WebSocketHeaderValue;
use tokio_tungstenite::tungstenite::protocol::frame::coding::CloseCode;
use tokio_tungstenite::tungstenite::protocol::{CloseFrame, WebSocketConfig};
use tokio_tungstenite::tungstenite::proxy::ProxyConfig;
use tokio_tungstenite::tungstenite::{Error as WebSocketError, Message};
use tungstenite::Bytes;
use tungstenite::extensions::ExtensionsConfig;
use tungstenite::extensions::compression::deflate::DeflateConfig;
use url::Url;

use crate::http::error_chain_has_invalid_certificate;
use crate::runtime::{Output, emit};

pub(crate) trait AsyncIo: AsyncRead + AsyncWrite + Send + Unpin {}

impl<T> AsyncIo for T where T: AsyncRead + AsyncWrite + Send + Unpin {}

pub(crate) type NativeWebSocket =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<Box<dyn AsyncIo>>>;

pub(crate) enum WebSocketCommand {
    Send {
        command_id: String,
        message: Message,
    },
    Close {
        command_id: String,
        code: u16,
        reason: String,
    },
}

#[derive(Debug)]
pub(crate) enum NativeWebSocketFailure {
    Connect(WebSocketError),
    WebSocket(WebSocketError),
    Timeout,
    LivenessTimeout,
    ConsumerBackpressure,
    ReceiveWindow,
    Output(std::io::Error),
}

impl std::fmt::Display for NativeWebSocketFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Connect(error) => write!(formatter, "{error}"),
            Self::WebSocket(error) => write!(formatter, "{error}"),
            Self::Timeout => formatter.write_str("websocket connect timed out"),
            Self::LivenessTimeout => formatter.write_str("websocket pong timed out"),
            Self::ConsumerBackpressure => {
                formatter.write_str("websocket retained payload exceeds 32 MiB")
            }
            Self::ReceiveWindow => {
                formatter.write_str("websocket receive receipt has no matching data")
            }
            Self::Output(error) => write!(formatter, "{error}"),
        }
    }
}

impl std::error::Error for NativeWebSocketFailure {}

impl From<WebSocketError> for NativeWebSocketFailure {
    fn from(error: WebSocketError) -> Self {
        Self::WebSocket(error)
    }
}

impl From<std::io::Error> for NativeWebSocketFailure {
    fn from(error: std::io::Error) -> Self {
        Self::Output(error)
    }
}

// Receive receipts release both a Python slot and its retained byte charge.
// The native pending queue applies TCP backpressure without blocking commands.
const RECEIVE_WINDOW: usize = 64;
const RECEIVE_BYTES: usize = 32 * 1024 * 1024;

#[derive(Default)]
struct ReceiveWindow {
    pending: VecDeque<(NativeEvent, usize)>,
    in_flight: VecDeque<usize>,
    retained_bytes: usize,
}

impl ReceiveWindow {
    fn push(&mut self, event: NativeEvent) -> Result<(), NativeWebSocketFailure> {
        let charge = payload_charge(&event);
        if charge > RECEIVE_BYTES.saturating_sub(self.retained_bytes) {
            return Err(NativeWebSocketFailure::ConsumerBackpressure);
        }
        self.retained_bytes += charge;
        self.pending.push_back((event, charge));
        Ok(())
    }

    fn consumed(&mut self) -> Result<(), NativeWebSocketFailure> {
        let charge = self
            .in_flight
            .pop_front()
            .ok_or(NativeWebSocketFailure::ReceiveWindow)?;
        self.retained_bytes -= charge;
        Ok(())
    }
}

fn payload_charge(event: &NativeEvent) -> usize {
    match event {
        NativeEvent::WebsocketText { text, .. } => text.len(),
        NativeEvent::WebsocketResponsesText {
            text,
            payload,
            event_type,
            payload_response_id,
            sequence_number,
            ..
        } => {
            text.len()
                + payload.get().len()
                + event_type.as_ref().map_or(0, String::len)
                + payload_response_id.as_ref().map_or(0, String::len)
                + sequence_number
                    .as_ref()
                    .map_or(0, |value| value.get().len())
        }
        NativeEvent::WebsocketBinary { data, .. } => {
            let padding = data.bytes().rev().take_while(|byte| *byte == b'=').count();
            data.len() + (data.len() / 4 * 3).saturating_sub(padding)
        }
        _ => 0,
    }
}

async fn deliver_or_queue(
    output: &Output,
    event: NativeEvent,
    enabled: bool,
    window: &mut ReceiveWindow,
) -> Result<(), NativeWebSocketFailure> {
    if enabled {
        window.push(event)
    } else {
        emit(output, &event).await.map_err(Into::into)
    }
}

pub(crate) async fn execute_websocket(
    request: NativeWebSocketRequest,
    mut commands: mpsc::Receiver<WebSocketCommand>,
    mut consumed: mpsc::Receiver<()>,
    output: &Output,
) -> Result<(), NativeWebSocketFailure> {
    let request_id = request.request_id.clone();
    let connect_timeout = Duration::from_millis(request.connect_timeout_ms);
    let connected = tokio::time::timeout(connect_timeout, connect_native_websocket(&request))
        .await
        .map_err(|_| NativeWebSocketFailure::Timeout)?
        .map_err(NativeWebSocketFailure::Connect)?;
    let (websocket, response) = connected;
    let mut websocket = Some(websocket);
    let response_headers = websocket_headers(response.headers());
    emit(
        output,
        &NativeEvent::WebsocketOpen {
            request_id: request_id.clone(),
            status: response.status().as_u16(),
            headers: response_headers,
        },
    )
    .await?;

    let ping_interval = request.ping_interval_ms.map(Duration::from_millis);
    let ping_timeout = request.ping_timeout_ms.map(Duration::from_millis);
    let dormant_timer = Duration::from_secs(100 * 365 * 24 * 60 * 60);
    let mut next_ping = Box::pin(tokio::time::sleep(ping_interval.unwrap_or(dormant_timer)));
    let mut pong_deadline = Box::pin(tokio::time::sleep(dormant_timer));
    let mut ping_sequence = 0_u64;
    let mut awaiting_pong = None;
    let enabled = request.receive_backpressure;
    let mut window = ReceiveWindow::default();
    let mut source_closed = false;

    loop {
        tokio::select! {
            receipt = consumed.recv(), if enabled => {
                if receipt.is_none() {
                    return Ok(());
                }
                window.consumed()?;
            }
            _ = std::future::ready(()), if enabled && !window.pending.is_empty() && window.in_flight.len() < RECEIVE_WINDOW => {
                let (event, charge) = window.pending.pop_front().expect("guarded pending data");
                let terminal = matches!(event, NativeEvent::WebsocketClose { .. });
                emit(output, &event).await?;
                if terminal {
                    return Ok(());
                }
                window.in_flight.push_back(charge);
            }
            _ = &mut next_ping, if !source_closed && ping_interval.is_some() => {
                let interval = ping_interval.expect("guarded ping interval");
                next_ping.as_mut().reset(tokio::time::Instant::now() + interval);
                if awaiting_pong.is_none() {
                    ping_sequence = ping_sequence.wrapping_add(1);
                    let payload = Bytes::copy_from_slice(&ping_sequence.to_be_bytes());
                    websocket.as_mut().expect("open transport").send(Message::Ping(payload.clone())).await?;
                    if let Some(timeout) = ping_timeout {
                        awaiting_pong = Some(payload);
                        pong_deadline.as_mut().reset(tokio::time::Instant::now() + timeout);
                    }
                }
            }
            _ = &mut pong_deadline, if !source_closed && awaiting_pong.is_some() => {
                return Err(NativeWebSocketFailure::LivenessTimeout);
            }
            command = commands.recv() => {
                let Some(command) = command else {
                    return Ok(());
                };
                let Some(websocket) = websocket.as_mut() else {
                    match command {
                        WebSocketCommand::Send { command_id, .. } => {
                            // The transport is gone, but the ordered receive
                            // window still owns data and its terminal event.
                            emit(output, &NativeEvent::WebsocketError {
                                request_id: request_id.clone(),
                                command_id: Some(command_id),
                                message: "native websocket is closed".to_owned(),
                                failure_phase: "websocket_send".to_owned(),
                                retryable_same_contract: false,
                                is_tls_verification_failure: false,
                                status: None,
                                headers: Vec::new(),
                                body: None,
                            }).await?;
                        }
                        WebSocketCommand::Close { command_id, code, reason } => {
                            // Explicit local close may retire unread data, as
                            // before; it never waits for application receipts.
                            emit(output, &NativeEvent::WebsocketSent {
                                request_id: request_id.clone(), command_id,
                            }).await?;
                            emit(output, &NativeEvent::WebsocketClose {
                                request_id: request_id.clone(), code: Some(code),
                                reason: (!reason.is_empty()).then_some(reason),
                            }).await?;
                            return Ok(());
                        }
                    }
                    continue;
                };
                match command {
                    WebSocketCommand::Send { command_id, message } => {
                        match websocket.send(message).await {
                            Ok(()) => {
                                emit(
                                    output,
                                    &NativeEvent::WebsocketSent {
                                        request_id: request_id.clone(),
                                        command_id,
                                    },
                                ).await?;
                            }
                            Err(error) => {
                                emit_websocket_error(
                                    output,
                                    &request_id,
                                    Some(command_id),
                                    &NativeWebSocketFailure::WebSocket(error),
                                ).await?;
                                return Ok(());
                            }
                        }
                    }
                    WebSocketCommand::Close { command_id, code, reason } => {
                        let frame = CloseFrame {
                            code: CloseCode::from(code),
                            reason: reason.clone().into(),
                        };
                        match websocket.send(Message::Close(Some(frame))).await {
                            Ok(()) => {
                                emit(
                                    output,
                                    &NativeEvent::WebsocketSent {
                                        request_id: request_id.clone(),
                                        command_id,
                                    },
                                ).await?;
                                emit(
                                    output,
                                    &NativeEvent::WebsocketClose {
                                        request_id,
                                        code: Some(code),
                                        reason: (!reason.is_empty()).then_some(reason),
                                    },
                                ).await?;
                                return Ok(());
                            }
                            Err(error) => {
                                emit_websocket_error(
                                    output,
                                    &request_id,
                                    Some(command_id),
                                    &NativeWebSocketFailure::WebSocket(error),
                                ).await?;
                                return Ok(());
                            }
                        }
                    }
                }
            }
            incoming = async { websocket.as_mut().expect("open transport").next().await }, if !source_closed && (!enabled || window.pending.len() < RECEIVE_WINDOW) => {
                match incoming {
                    Some(Ok(Message::Text(text))) => {
                        let text = text.to_string();
                        let event = request
                            .interpret_responses
                            .then(|| interpret_websocket(&text))
                            .flatten();
                        if let Some(event) = event {
                            deliver_or_queue(
                                output,
                                NativeEvent::WebsocketResponsesText {
                                    request_id: request_id.clone(),
                                    text,
                                    event_type: event.event_type,
                                    payload: event.payload,
                                    payload_response_id: event.payload_response_id,
                                    sequence_number: event.sequence_number,
                                },
                                enabled, &mut window,
                            )
                            .await?;
                        } else {
                            deliver_or_queue(
                                output,
                                NativeEvent::WebsocketText {
                                    request_id: request_id.clone(),
                                    text,
                                },
                                enabled, &mut window,
                            )
                            .await?;
                        }
                    }
                    Some(Ok(Message::Binary(data))) => {
                        deliver_or_queue(
                            output,
                            NativeEvent::WebsocketBinary {
                                request_id: request_id.clone(),
                                data: base64::engine::general_purpose::STANDARD.encode(data),
                            },
                            enabled, &mut window,
                        ).await?;
                    }
                    Some(Ok(Message::Ping(payload))) => {
                        if let Err(error) = websocket.as_mut().expect("open transport").send(Message::Pong(payload)).await {
                            return Err(error.into());
                        }
                    }
                    Some(Ok(Message::Pong(payload))) => {
                        if awaiting_pong.as_ref().is_some_and(|expected| expected == &payload) {
                            awaiting_pong = None;
                        }
                    }
                    Some(Ok(Message::Close(frame))) => {
                        // Pinned tungstenite queues the close reply on read;
                        // tokio-tungstenite flush writes it but does not shut
                        // down TCP. Release the flushed transport now, not when
                        // application credits finally drain the receive window.
                        websocket.as_mut().expect("open transport").flush().await?;
                        drop(websocket.take());
                        let (code, reason) = frame
                            .map(|frame| {
                                (
                                    Some(u16::from(frame.code)),
                                    (!frame.reason.is_empty()).then(|| frame.reason.to_string()),
                                )
                            })
                            .unwrap_or((None, None));
                        deliver_or_queue(
                            output,
                            NativeEvent::WebsocketClose { request_id: request_id.clone(), code, reason },
                            enabled, &mut window,
                        ).await?;
                        if !enabled { return Ok(()); }
                        source_closed = true;
                    }
                    Some(Ok(Message::Frame(_))) => {}
                    Some(Err(error)) => return Err(error.into()),
                    None => {
                        drop(websocket.take());
                        deliver_or_queue(
                            output,
                            NativeEvent::WebsocketClose {
                                request_id: request_id.clone(),
                                code: None,
                                reason: None,
                            },
                            enabled, &mut window,
                        ).await?;
                        if !enabled { return Ok(()); }
                        source_closed = true;
                    }
                }
            }
        }
    }
}

pub(crate) async fn connect_native_websocket(
    native_request: &NativeWebSocketRequest,
) -> Result<(NativeWebSocket, WebSocketResponse), WebSocketError> {
    let mut request = native_request.url.as_str().into_client_request()?;
    for (name, value) in &native_request.headers {
        request.headers_mut().append(
            WebSocketHeaderName::from_bytes(name.as_bytes())?,
            WebSocketHeaderValue::from_str(value)?,
        );
    }

    let host = request
        .uri()
        .host()
        .ok_or(tokio_tungstenite::tungstenite::error::UrlError::NoHostName)?
        .to_owned();
    let port = request
        .uri()
        .port_u16()
        .or_else(|| match request.uri().scheme_str() {
            Some("ws") => Some(80),
            Some("wss") => Some(443),
            _ => None,
        })
        .ok_or(tokio_tungstenite::tungstenite::error::UrlError::UnsupportedUrlScheme)?;

    let tls_config = native_tls_config()?;
    let stream: Box<dyn AsyncIo> = match native_request.proxy_url.as_deref() {
        None => Box::new(TcpStream::connect(host_port(&host, port)).await?),
        Some(proxy_url) => {
            let proxy = ProxyEndpoint::parse(proxy_url)?;
            let stream = TcpStream::connect(proxy.config.authority()).await?;
            let stream: Box<dyn AsyncIo> = if proxy.tls {
                let server_name = rustls::pki_types::ServerName::try_from(
                    proxy.config.host.clone(),
                )
                .map_err(|_| tokio_tungstenite::tungstenite::error::TlsError::InvalidDnsName)?;
                Box::new(
                    TlsConnector::from(tls_config.clone())
                        .connect(server_name, stream)
                        .await
                        .map_err(WebSocketError::Io)?,
                )
            } else {
                Box::new(stream)
            };
            Box::new(connect_via_proxy(stream, &proxy.config, &host, port).await?)
        }
    };

    client_async_tls_with_config(
        request,
        stream,
        Some(native_websocket_config(native_request.max_message_bytes)),
        Some(Connector::Rustls(tls_config)),
    )
    .await
}

pub(crate) fn native_websocket_config(max_message_bytes: usize) -> WebSocketConfig {
    let mut extensions = ExtensionsConfig::default();
    extensions.permessage_deflate = Some(DeflateConfig::default());
    let mut config = WebSocketConfig::default();
    config.max_message_size = Some(max_message_bytes);
    config.extensions = extensions;
    config
}

fn native_tls_config() -> Result<Arc<ClientConfig>, WebSocketError> {
    let certificates = rustls_native_certs::load_native_certs();
    let mut roots = RootCertStore::empty();
    roots.add_parsable_certificates(certificates.certs);
    if roots.is_empty() {
        return Err(WebSocketError::Io(std::io::Error::other(
            "native certificate store is empty",
        )));
    }
    Ok(Arc::new(
        ClientConfig::builder()
            .with_root_certificates(roots)
            .with_no_client_auth(),
    ))
}

#[derive(Debug)]
struct ProxyEndpoint {
    config: ProxyConfig,
    tls: bool,
}

impl ProxyEndpoint {
    fn parse(value: &str) -> Result<Self, WebSocketError> {
        let mut url = Url::parse(value).map_err(|_| invalid_proxy_config())?;
        let tls = url.scheme() == "https";
        if tls {
            let port = url
                .port_or_known_default()
                .ok_or_else(invalid_proxy_config)?;
            url.set_scheme("http").map_err(|_| invalid_proxy_config())?;
            url.set_port(Some(port))
                .map_err(|_| invalid_proxy_config())?;
        }
        let config = ProxyConfig::parse(url.as_str()).map_err(|_| invalid_proxy_config())?;
        Ok(Self { config, tls })
    }
}

fn invalid_proxy_config() -> WebSocketError {
    WebSocketError::Url(
        tokio_tungstenite::tungstenite::error::UrlError::InvalidProxyConfig(
            "<redacted>".to_owned(),
        ),
    )
}

fn host_port(host: &str, port: u16) -> String {
    if host.contains(':') && !host.starts_with('[') {
        format!("[{host}]:{port}")
    } else {
        format!("{host}:{port}")
    }
}

fn websocket_headers(
    headers: &tokio_tungstenite::tungstenite::http::HeaderMap,
) -> Vec<(String, String)> {
    headers
        .iter()
        .map(|(name, value)| {
            (
                name.as_str().to_owned(),
                String::from_utf8_lossy(value.as_bytes()).into_owned(),
            )
        })
        .collect()
}

pub(crate) async fn emit_websocket_setup_error(
    output: &Output,
    request_id: &str,
    command_id: Option<String>,
    message: &str,
) -> Result<(), std::io::Error> {
    emit(
        output,
        &NativeEvent::WebsocketError {
            request_id: request_id.to_owned(),
            command_id,
            message: message.to_owned(),
            failure_phase: "setup".to_owned(),
            retryable_same_contract: false,
            is_tls_verification_failure: false,
            status: None,
            headers: Vec::new(),
            body: None,
        },
    )
    .await
}

pub(crate) async fn emit_websocket_error(
    output: &Output,
    request_id: &str,
    command_id: Option<String>,
    failure: &NativeWebSocketFailure,
) -> Result<(), std::io::Error> {
    let (message, phase, retryable, tls_verification, status, headers, body) = match failure {
        NativeWebSocketFailure::ConsumerBackpressure => (
            "native websocket retained payload exceeds 32 MiB",
            "consumer_backpressure",
            false,
            false,
            None,
            Vec::new(),
            None,
        ),
        NativeWebSocketFailure::ReceiveWindow => (
            "native websocket receive receipt has no matching data",
            "protocol",
            false,
            false,
            None,
            Vec::new(),
            None,
        ),
        NativeWebSocketFailure::Timeout => (
            "native websocket connection timed out",
            "connect",
            true,
            false,
            None,
            Vec::new(),
            None,
        ),
        NativeWebSocketFailure::LivenessTimeout => (
            "native websocket pong timed out",
            "liveness_timeout",
            false,
            false,
            None,
            Vec::new(),
            None,
        ),
        NativeWebSocketFailure::Connect(WebSocketError::Http(response)) => (
            "native websocket handshake failed",
            "connect",
            false,
            false,
            Some(response.status().as_u16()),
            websocket_headers(response.headers()),
            response
                .body()
                .as_ref()
                .map(|body| base64::engine::general_purpose::STANDARD.encode(body)),
        ),
        NativeWebSocketFailure::Connect(WebSocketError::Io(_)) => {
            let tls_verification = websocket_tls_verification_failure(failure);
            (
                "native websocket transport failed",
                "connect",
                !tls_verification,
                tls_verification,
                None,
                Vec::new(),
                None,
            )
        }
        NativeWebSocketFailure::Connect(_) => {
            let tls_verification = websocket_tls_verification_failure(failure);
            (
                "native websocket connection failed",
                "connect",
                !tls_verification,
                tls_verification,
                None,
                Vec::new(),
                None,
            )
        }
        NativeWebSocketFailure::WebSocket(WebSocketError::Io(_)) => (
            "native websocket transport failed",
            "transport",
            false,
            websocket_tls_verification_failure(failure),
            None,
            Vec::new(),
            None,
        ),
        NativeWebSocketFailure::WebSocket(_) => (
            "native websocket protocol failed",
            "protocol",
            false,
            websocket_tls_verification_failure(failure),
            None,
            Vec::new(),
            None,
        ),
        NativeWebSocketFailure::Output(_) => (
            "native helper output failed",
            "helper_write",
            false,
            false,
            None,
            Vec::new(),
            None,
        ),
    };
    emit(
        output,
        &NativeEvent::WebsocketError {
            request_id: request_id.to_owned(),
            command_id,
            message: message.to_owned(),
            failure_phase: phase.to_owned(),
            retryable_same_contract: retryable,
            is_tls_verification_failure: tls_verification,
            status,
            headers,
            body,
        },
    )
    .await
}

fn websocket_tls_verification_failure(failure: &NativeWebSocketFailure) -> bool {
    match failure {
        NativeWebSocketFailure::Connect(WebSocketError::Tls(TlsError::Rustls(error)))
        | NativeWebSocketFailure::WebSocket(WebSocketError::Tls(TlsError::Rustls(error))) => {
            matches!(error.as_ref(), rustls::Error::InvalidCertificate(_))
        }
        NativeWebSocketFailure::Connect(error) | NativeWebSocketFailure::WebSocket(error) => {
            error_chain_has_invalid_certificate(error)
        }
        _ => false,
    }
}

#[cfg(test)]
mod receive_tests {
    use super::*;

    #[test]
    fn receipts_release_exactly_one_fifo_charge() {
        let mut window = ReceiveWindow::default();
        assert!(matches!(
            window.consumed(),
            Err(NativeWebSocketFailure::ReceiveWindow)
        ));
        for text in ["é", "abc"] {
            window
                .push(NativeEvent::WebsocketText {
                    request_id: "test".into(),
                    text: text.into(),
                })
                .unwrap();
        }
        assert_eq!(window.retained_bytes, 5);
        while let Some((_, charge)) = window.pending.pop_front() {
            window.in_flight.push_back(charge);
        }
        window.consumed().unwrap();
        assert_eq!(window.retained_bytes, 3);
        window.consumed().unwrap();
        assert_eq!(window.retained_bytes, 0);
        assert!(matches!(
            window.consumed(),
            Err(NativeWebSocketFailure::ReceiveWindow)
        ));
    }

    #[test]
    fn byte_budget_accepts_exact_edge_and_rejects_one_more_byte() {
        let mut window = ReceiveWindow::default();
        for _ in 0..2 {
            window
                .push(NativeEvent::WebsocketText {
                    request_id: "test".into(),
                    text: "x".repeat(RECEIVE_BYTES / 2),
                })
                .unwrap();
        }
        assert_eq!(window.retained_bytes, RECEIVE_BYTES);
        assert!(matches!(
            window.push(NativeEvent::WebsocketText {
                request_id: "test".into(),
                text: "x".into(),
            }),
            Err(NativeWebSocketFailure::ConsumerBackpressure)
        ));
        assert_eq!(window.pending.len(), 2);
        assert_eq!(window.retained_bytes, RECEIVE_BYTES);
    }

    #[test]
    fn binary_charge_includes_encoded_and_decoded_bytes() {
        for (data, charge) in [("YQ==", 5), ("YWI=", 6), ("YWJj", 7)] {
            assert_eq!(
                payload_charge(&NativeEvent::WebsocketBinary {
                    request_id: "test".into(),
                    data: data.into(),
                }),
                charge
            );
        }
    }
}
