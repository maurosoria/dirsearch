# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import base64
import struct

from ntlm_auth.constants import NegotiateFlags
from ntlm_auth.exceptions import NoAuthContextError
from ntlm_auth.messages import AuthenticateMessage, ChallengeMessage, \
    NegotiateMessage
from ntlm_auth.session_security import SessionSecurity


class NtlmContext(object):

    def __init__(self, username, password, domain=None, workstation=None,
                 cbt_data=None, ntlm_compatibility=3):
        r"""
        Initialises a NTLM context to use when authenticating using the NTLM
        protocol.
        Initialises the NTLM context to use when sending and receiving messages
        to and from the server. You should be using this object as it supports
        NTLMv2 authenticate and it easier to use than before. It also brings in
        the ability to use signing and sealing with session_security and
        generate a MIC structure.

        :param username: The username to authenticate with
        :param password: The password for the username
        :param domain: The domain part of the username (None if n/a)
        :param workstation: The localworkstation (None if n/a)
        :param cbt_data: A GssChannelBindingsStruct or None to bind channel
            data with the auth process
        :param ntlm_compatibility: (Default 3)
            The Lan Manager Compatibility Level to use with the auth message
            This is set by an Administrator in the registry key
            'HKLM\SYSTEM\CurrentControlSet\Control\Lsa\LmCompatibilityLevel'
            The values correspond to the following;
                0 : LM and NTLMv1
                1 : LM, NTLMv1 and NTLMv1 with Extended Session Security
                2 : NTLMv1 and NTLMv1 with Extended Session Security
                3-5 : NTLMv2 Only
            Note: Values 3 to 5 are no different from a client perspective
        """
        self.username = username
        self.password = password
        self.domain = domain
        self.workstation = workstation
        self.cbt_data = cbt_data
        self._server_certificate_hash = None  # deprecated for backwards compat
        self.ntlm_compatibility = ntlm_compatibility
        self.complete = False

        # Setting up our flags so the challenge message returns the target info
        # block if supported
        self.negotiate_flags = NegotiateFlags.NTLMSSP_NEGOTIATE_TARGET_INFO | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_128 | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_56 | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_UNICODE | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_VERSION | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_KEY_EXCH | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_ALWAYS_SIGN | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_SIGN | \
            NegotiateFlags.NTLMSSP_NEGOTIATE_SEAL

        # Setting the message types based on the ntlm_compatibility level
        self._set_ntlm_compatibility_flags(self.ntlm_compatibility)

        self._negotiate_message = None
        self._challenge_message = None
        self._authenticate_message = None
        self._session_security = None

    @property
    def mic_present(self):
        if self._authenticate_message:
            return bool(self._authenticate_message.mic)

        return False

    @property
    def session_key(self):
        if self._authenticate_message:
            return self._authenticate_message.exported_session_key

    def reset_rc4_state(self, outgoing=True):
        """ Resets the signing cipher for the incoming or outgoing cipher. For SPNEGO for calculating mechListMIC. """
        if self._session_security:
            self._session_security.reset_rc4_state(outgoing=outgoing)

    def step(self, input_token=None):
        if self._negotiate_message is None:
            self._negotiate_message = NegotiateMessage(self.negotiate_flags,
                                                       self.domain,
                                                       self.workstation)
            return self._negotiate_message.get_data()
        else:
            self._challenge_message = ChallengeMessage(input_token)
            self._authenticate_message = AuthenticateMessage(
                self.username, self.password, self.domain, self.workstation,
                self._challenge_message, self.ntlm_compatibility,
                server_certificate_hash=self._server_certificate_hash,
                cbt_data=self.cbt_data
            )
            self._authenticate_message.add_mic(self._negotiate_message,
                                               self._challenge_message)

            flag_bytes = self._authenticate_message.negotiate_flags
            flags = struct.unpack("<I", flag_bytes)[0]
            if flags & NegotiateFlags.NTLMSSP_NEGOTIATE_SEAL or \
                    flags & NegotiateFlags.NTLMSSP_NEGOTIATE_SIGN:
                self._session_security = SessionSecurity(
                    flags, self.session_key
                )

            self.complete = True
            return self._authenticate_message.get_data()

    def sign(self, data):
        return self._session_security.get_signature(data)

    def verify(self, data, signature):
        self._session_security.verify_signature(data, signature)

    def wrap(self, data):
        if self._session_security is None:
            raise NoAuthContextError("Cannot wrap data as no security context "
                                     "has been established")

        data, header = self._session_security.wrap(data)
        return header + data

    def unwrap(self, data):
        if self._session_security is None:
            raise NoAuthContextError("Cannot unwrap data as no security "
                                     "context has been established")
        header = data[0:16]
        data = data[16:]
        message = self._session_security.unwrap(data, header)
        return message

    def _set_ntlm_compatibility_flags(self, ntlm_compatibility):
        if (ntlm_compatibility >= 0) and (ntlm_compatibility <= 5):
            if ntlm_compatibility == 0:
                self.negotiate_flags |= \
                    NegotiateFlags.NTLMSSP_NEGOTIATE_NTLM | \
                    NegotiateFlags.NTLMSSP_NEGOTIATE_LM_KEY
            elif ntlm_compatibility == 1:
                self.negotiate_flags |= \
                    NegotiateFlags.NTLMSSP_NEGOTIATE_NTLM | \
                    NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY
            else:
                self.negotiate_flags |= \
                    NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY
        else:
            raise Exception("Unknown ntlm_compatibility level - "
                            "expecting value between 0 and 5")


# Deprecated in favour of NtlmContext - this current class is heavily geared
# towards a HTTP API which is not always the case with NTLM. This is currently
# just a thin wrapper over NtlmContext and will be removed in future ntlm-auth
# versions
class Ntlm(object):

    def __init__(self, ntlm_compatibility=3):
        self._context = NtlmContext(None, None,
                                    ntlm_compatibility=ntlm_compatibility)
        self._challenge_token = None

    @property
    def negotiate_flags(self):
        return self._context.negotiate_flags

    @negotiate_flags.setter
    def negotiate_flags(self, value):
        self._context.negotiate_flags = value

    @property
    def ntlm_compatibility(self):
        return self._context.ntlm_compatibility

    @ntlm_compatibility.setter
    def ntlm_compatibility(self, value):
        self._context.ntlm_compatibility = value

    @property
    def negotiate_message(self):
        return self._context._negotiate_message

    @negotiate_message.setter
    def negotiate_message(self, value):
        self._context._negotiate_message = value

    @property
    def challenge_message(self):
        return self._context._challenge_message

    @challenge_message.setter
    def challenge_message(self, value):
        self._context._challenge_message = value

    @property
    def authenticate_message(self):
        return self._context._authenticate_message

    @authenticate_message.setter
    def authenticate_message(self, value):
        self._context._authenticate_message = value

    @property
    def session_security(self):
        return self._context._session_security

    @session_security.setter
    def session_security(self, value):
        self._context._session_security = value

    def create_negotiate_message(self, domain_name=None, workstation=None):
        self._context.domain = domain_name
        self._context.workstation = workstation
        msg = self._context.step()
        return base64.b64encode(msg)

    def parse_challenge_message(self, msg2):
        self._challenge_token = base64.b64decode(msg2)

    def create_authenticate_message(self, user_name, password,
                                    domain_name=None, workstation=None,
                                    server_certificate_hash=None):
        self._context.username = user_name
        self._context.password = password
        self._context.domain = domain_name
        self._context.workstation = workstation
        self._context._server_certificate_hash = server_certificate_hash
        msg = self._context.step(self._challenge_token)
        return base64.b64encode(msg)
