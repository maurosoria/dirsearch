//! NTLMv2 token generation and TLS channel binding.

use hmac::{Hmac, Mac};
use md5::Md5;
use ntlmclient::{
    get_ntlm_time, respond_challenge_ntlm_v2, Credentials, Flags, Message, NegotiateMessage,
    OsVersion, TargetInfoEntry, TargetInfoType,
};
use picky_asn1_x509::{AlgorithmIdentifierParameters, Certificate, HashAlgorithm};
use sha2::{Digest, Sha224, Sha256, Sha384, Sha512};
use sha3::{Sha3_224, Sha3_256, Sha3_384, Sha3_512};
use zeroize::Zeroize;

const TLS_SERVER_END_POINT_PREFIX: &[u8] = b"tls-server-end-point:";
const NTLM_MIC_LENGTH: usize = 16;
const NTLM_TYPE3_VERSION_OFFSET: usize = 64;
const NTLM_TYPE3_VERSION_LENGTH: usize = 8;
const NTLM_TYPE3_SECURITY_BUFFERS: [usize; 6] = [12, 20, 28, 36, 44, 52];

/// One connection-bound NTLMv2 exchange.
///
/// A new value is created for every HTTP authentication handshake. The
/// temporary credential copy is zeroized immediately after the Type 3 token
/// is produced.
pub(crate) struct NtlmExchange<'a> {
    password: &'a str,
    domain: String,
    account: String,
    target_name: String,
    negotiate: Option<Vec<u8>>,
}

impl<'a> NtlmExchange<'a> {
    pub(crate) fn new(
        username: &'a str,
        password: &'a str,
        target_host: &str,
    ) -> Result<Self, String> {
        let (domain, account) = split_username(username)?;

        Ok(Self {
            password,
            domain,
            account,
            target_name: format!("HTTP/{target_host}"),
            negotiate: None,
        })
    }

    pub(crate) fn negotiate_token(&mut self) -> Result<Vec<u8>, String> {
        let message = Message::Negotiate(NegotiateMessage {
            flags: requested_flags(),
            supplied_domain: String::new(),
            supplied_workstation: String::new(),
            os_version: OsVersion::default(),
        });
        let token = message
            .to_bytes()
            .map_err(|error| format!("Could not create NTLM negotiate token: {error}"))?;
        self.negotiate = Some(token.clone());
        Ok(token)
    }

    pub(crate) fn authenticate_token(
        &mut self,
        challenge: Vec<u8>,
        channel_bindings: Option<&[u8]>,
    ) -> Result<Vec<u8>, String> {
        let negotiate = self
            .negotiate
            .as_deref()
            .ok_or_else(|| "NTLM challenge arrived before the negotiate token".to_string())?;
        let challenge_message = match Message::try_from(challenge.as_slice())
            .map_err(|error| format!("Could not parse NTLM challenge: {error}"))?
        {
            Message::Challenge(challenge) => challenge,
            _ => return Err("NTLM server returned a non-challenge token".to_string()),
        };
        let required = Flags::NEGOTIATE_UNICODE
            | Flags::NEGOTIATE_NTLM
            | Flags::NEGOTIATE_NTLM2_KEY
            | Flags::NEGOTIATE_TARGET_INFO;
        if !challenge_message.flags.contains(required) {
            return Err("NTLM server challenge does not support secure NTLMv2".to_string());
        }

        let mut target_information = challenge_message
            .target_information
            .iter()
            .filter(|entry| {
                !matches!(
                    entry.entry_type,
                    TargetInfoType::Terminator
                        | TargetInfoType::Flags
                        | TargetInfoType::TargetName
                        | TargetInfoType::ChannelBindings
                )
            })
            .cloned()
            .collect::<Vec<_>>();
        target_information.push(TargetInfoEntry {
            entry_type: TargetInfoType::Flags,
            // MsvAvFlags::MIC_PROVIDED
            data: 0x0000_0002u32.to_le_bytes().to_vec(),
        });
        target_information.push(TargetInfoEntry::from_string(
            TargetInfoType::TargetName,
            &self.target_name,
        ));
        if let Some(channel_bindings) = channel_bindings {
            target_information.push(TargetInfoEntry {
                entry_type: TargetInfoType::ChannelBindings,
                data: channel_binding_hash(channel_bindings).to_vec(),
            });
        }
        target_information.push(TargetInfoEntry {
            entry_type: TargetInfoType::Terminator,
            data: Vec::new(),
        });
        let target_information = target_information
            .iter()
            .flat_map(TargetInfoEntry::to_bytes)
            .collect::<Vec<_>>();
        let timestamp = challenge_message
            .target_information
            .iter()
            .find(|entry| entry.entry_type == TargetInfoType::Timestamp)
            .and_then(|entry| entry.data.as_slice().try_into().ok())
            .map(i64::from_le_bytes)
            .unwrap_or_else(get_ntlm_time);
        let mut credentials = Credentials {
            username: self.account.clone(),
            password: self.password.to_string(),
            domain: self.domain.clone(),
        };
        let response = respond_challenge_ntlm_v2(
            challenge_message.challenge,
            &target_information,
            timestamp,
            &credentials,
        );
        credentials.password.zeroize();
        let exported_session_key = response.session_key.clone();
        let negotiated_flags = challenge_message.flags & requested_flags();
        let mut authenticate = match response.to_message(&credentials, "", negotiated_flags) {
            Message::Authenticate(authenticate) => authenticate,
            _ => unreachable!("NTLM challenge response always creates an authenticate message"),
        };
        // Key exchange is deliberately not offered. Without it, the exported
        // session key is the response session key and this field must be empty.
        authenticate.session_key.clear();
        let token = Message::Authenticate(authenticate)
            .to_bytes()
            .map_err(|error| format!("Could not create NTLM authenticate token: {error}"))?;
        add_message_integrity_code(
            token,
            negotiate,
            &challenge,
            &exported_session_key,
            negotiated_flags.contains(Flags::NEGOTIATE_VERSION),
        )
    }
}

fn requested_flags() -> Flags {
    Flags::NEGOTIATE_UNICODE
        | Flags::REQUEST_TARGET
        | Flags::NEGOTIATE_NTLM
        | Flags::NEGOTIATE_ALWAYS_SIGN
        | Flags::NEGOTIATE_NTLM2_KEY
        | Flags::NEGOTIATE_TARGET_INFO
        | Flags::NEGOTIATE_VERSION
        | Flags::NEGOTIATE_128BIT
        | Flags::NEGOTIATE_56BIT
}

pub(crate) fn split_username(username: &str) -> Result<(String, String), String> {
    let (domain, account, domain_was_explicit) =
        if let Some((domain, account)) = username.split_once('\\') {
            (domain, account, true)
        } else if let Some((account, domain)) = username.rsplit_once('@') {
            (domain, account, true)
        } else {
            ("", username, false)
        };
    if account.is_empty() || (domain_was_explicit && domain.is_empty()) {
        return Err("Invalid NTLM username".to_string());
    }
    Ok((domain.to_string(), account.to_string()))
}

pub(crate) fn channel_binding_hash(channel_bindings: &[u8]) -> [u8; NTLM_MIC_LENGTH] {
    let mut bindings = Vec::with_capacity(20 + channel_bindings.len());
    bindings.extend_from_slice(&[0; 16]);
    bindings.extend_from_slice(&(channel_bindings.len() as u32).to_le_bytes());
    bindings.extend_from_slice(channel_bindings);
    <Md5 as md5::Digest>::digest(bindings).into()
}

fn add_message_integrity_code(
    mut authenticate: Vec<u8>,
    negotiate: &[u8],
    challenge: &[u8],
    exported_session_key: &[u8],
    has_version: bool,
) -> Result<Vec<u8>, String> {
    if authenticate.len() < NTLM_TYPE3_VERSION_OFFSET + NTLM_TYPE3_VERSION_LENGTH {
        return Err("NTLM authenticate token is truncated".to_string());
    }
    if !has_version {
        authenticate.drain(
            NTLM_TYPE3_VERSION_OFFSET..NTLM_TYPE3_VERSION_OFFSET + NTLM_TYPE3_VERSION_LENGTH,
        );
        adjust_type3_payload_offsets(&mut authenticate, -(NTLM_TYPE3_VERSION_LENGTH as i32))?;
    }
    let mic_offset = NTLM_TYPE3_VERSION_OFFSET
        + if has_version {
            NTLM_TYPE3_VERSION_LENGTH
        } else {
            0
        };
    authenticate.splice(mic_offset..mic_offset, [0; NTLM_MIC_LENGTH]);
    adjust_type3_payload_offsets(&mut authenticate, NTLM_MIC_LENGTH as i32)?;

    type HmacMd5 = Hmac<Md5>;
    let mut mic = <HmacMd5 as Mac>::new_from_slice(exported_session_key)
        .map_err(|_| "Could not initialize NTLM message integrity code".to_string())?;
    mic.update(negotiate);
    mic.update(challenge);
    mic.update(&authenticate);
    authenticate[mic_offset..mic_offset + NTLM_MIC_LENGTH]
        .copy_from_slice(&mic.finalize().into_bytes());
    Ok(authenticate)
}

fn adjust_type3_payload_offsets(token: &mut [u8], adjustment: i32) -> Result<(), String> {
    for security_buffer in NTLM_TYPE3_SECURITY_BUFFERS {
        let offset_position = security_buffer + 4;
        let offset_bytes: [u8; 4] = token
            .get(offset_position..offset_position + 4)
            .ok_or_else(|| "NTLM authenticate security buffer is truncated".to_string())?
            .try_into()
            .unwrap();
        let offset = u32::from_le_bytes(offset_bytes);
        let offset = if adjustment.is_negative() {
            offset.checked_sub(adjustment.unsigned_abs())
        } else {
            offset.checked_add(adjustment as u32)
        }
        .ok_or_else(|| "NTLM authenticate security buffer offset overflowed".to_string())?;
        token[offset_position..offset_position + 4].copy_from_slice(&offset.to_le_bytes());
    }
    Ok(())
}

/// Build the GSS application data used by NTLM Extended Protection.
pub(crate) fn tls_server_end_point(certificate_der: &[u8]) -> Result<Vec<u8>, String> {
    let certificate: Certificate = picky_asn1_der::from_bytes(certificate_der)
        .map_err(|error| format!("Could not parse TLS certificate for NTLM CBT: {error}"))?;
    let hash = certificate_hash(certificate_der, &certificate)?;
    let mut channel_bindings = Vec::with_capacity(TLS_SERVER_END_POINT_PREFIX.len() + hash.len());
    channel_bindings.extend_from_slice(TLS_SERVER_END_POINT_PREFIX);
    channel_bindings.extend_from_slice(&hash);
    Ok(channel_bindings)
}

fn certificate_hash(certificate_der: &[u8], certificate: &Certificate) -> Result<Vec<u8>, String> {
    let algorithm = &certificate.signature_algorithm;
    let oid = Into::<String>::into(algorithm.oid());
    let hash = match oid.as_str() {
        // RFC 5929 promotes MD5 and SHA-1 certificate signatures to SHA-256.
        "1.2.840.113549.1.1.4" | "1.2.840.113549.1.1.5" | "1.2.840.10040.4.3" => {
            ChannelBindingHash::Sha256
        }
        "1.2.840.113549.1.1.14" | "1.2.840.10045.4.3.1" | "2.16.840.1.101.3.4.3.1" => {
            ChannelBindingHash::Sha224
        }
        "1.2.840.113549.1.1.11" | "1.2.840.10045.4.3.2" | "2.16.840.1.101.3.4.3.2" => {
            ChannelBindingHash::Sha256
        }
        "1.2.840.113549.1.1.12" | "1.2.840.10045.4.3.3" | "2.16.840.1.101.3.4.3.3" => {
            ChannelBindingHash::Sha384
        }
        "1.2.840.113549.1.1.13" | "1.2.840.10045.4.3.4" | "2.16.840.1.101.3.4.3.4" => {
            ChannelBindingHash::Sha512
        }
        "2.16.840.1.101.3.4.3.5" | "2.16.840.1.101.3.4.3.9" | "2.16.840.1.101.3.4.3.13" => {
            ChannelBindingHash::Sha3_224
        }
        "2.16.840.1.101.3.4.3.6" | "2.16.840.1.101.3.4.3.10" | "2.16.840.1.101.3.4.3.14" => {
            ChannelBindingHash::Sha3_256
        }
        "2.16.840.1.101.3.4.3.7" | "2.16.840.1.101.3.4.3.11" | "2.16.840.1.101.3.4.3.15" => {
            ChannelBindingHash::Sha3_384
        }
        "2.16.840.1.101.3.4.3.8" | "2.16.840.1.101.3.4.3.12" | "2.16.840.1.101.3.4.3.16" => {
            ChannelBindingHash::Sha3_512
        }
        "1.2.840.113549.1.1.10" => match algorithm.parameters() {
            AlgorithmIdentifierParameters::RsassaPss(parameters) => {
                ChannelBindingHash::from_pss(parameters.hash_algorithm)
            }
            _ => {
                return Err(
                    "TLS certificate has invalid RSA-PSS parameters for NTLM CBT".to_string(),
                )
            }
        },
        _ => {
            return Err(format!(
                "TLS certificate signature algorithm {oid} has no RFC 5929 NTLM CBT hash"
            ))
        }
    };
    Ok(hash.digest(certificate_der))
}

enum ChannelBindingHash {
    Sha224,
    Sha256,
    Sha384,
    Sha512,
    Sha3_224,
    Sha3_256,
    Sha3_384,
    Sha3_512,
}

impl ChannelBindingHash {
    fn from_pss(hash: HashAlgorithm) -> Self {
        match hash {
            HashAlgorithm::SHA224 => Self::Sha224,
            HashAlgorithm::SHA256 => Self::Sha256,
            HashAlgorithm::SHA384 => Self::Sha384,
            HashAlgorithm::SHA512 => Self::Sha512,
            HashAlgorithm::SHA3_224 => Self::Sha3_224,
            HashAlgorithm::SHA3_256 => Self::Sha3_256,
            HashAlgorithm::SHA3_384 => Self::Sha3_384,
            HashAlgorithm::SHA3_512 => Self::Sha3_512,
        }
    }

    fn digest(self, value: &[u8]) -> Vec<u8> {
        match self {
            Self::Sha224 => Sha224::digest(value).to_vec(),
            Self::Sha256 => Sha256::digest(value).to_vec(),
            Self::Sha384 => Sha384::digest(value).to_vec(),
            Self::Sha512 => Sha512::digest(value).to_vec(),
            Self::Sha3_224 => Sha3_224::digest(value).to_vec(),
            Self::Sha3_256 => Sha3_256::digest(value).to_vec(),
            Self::Sha3_384 => Sha3_384::digest(value).to_vec(),
            Self::Sha3_512 => Sha3_512::digest(value).to_vec(),
        }
    }
}
