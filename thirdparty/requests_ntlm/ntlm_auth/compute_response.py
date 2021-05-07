# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import base64
import calendar
import hashlib
import hmac
import os
import struct
import time

import ntlm_auth.compute_hash as comphash
import ntlm_auth.compute_keys as compkeys
import ntlm_auth.messages

from ntlm_auth.des import DES
from ntlm_auth.constants import AvId, AvFlags, NegotiateFlags
from ntlm_auth.gss_channel_bindings import GssChannelBindingsStruct


class ComputeResponse():

    def __init__(self, user_name, password, domain_name, challenge_message,
                 ntlm_compatibility):
        """
        Constructor for the response computations. This class will compute the
        various nt and lm challenge responses.

        :param user_name: The user name of the user we are trying to
            authenticate with
        :param password: The password of the user we are trying to authenticate
            with
        :param domain_name: The domain name of the user account we are
            authenticated with, default is None
        :param challenge_message: A ChallengeMessage object that was received
            from the server after the negotiate_message
        :param ntlm_compatibility: The Lan Manager Compatibility Level, used to
            determine what NTLM auth version to use, see Ntlm in ntlm.py for
            more details
        """
        self._user_name = user_name
        self._password = password
        self._domain_name = domain_name
        self._challenge_message = challenge_message
        self._negotiate_flags = challenge_message.negotiate_flags
        self._server_challenge = challenge_message.server_challenge
        self._server_target_info = challenge_message.target_info
        self._ntlm_compatibility = ntlm_compatibility
        self._client_challenge = os.urandom(8)

    def get_lm_challenge_response(self):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.3.1 - NTLM v1 Authentication
        3.3.2 - NTLM v2 Authentication

        This method returns the LmChallengeResponse key based on the
        ntlm_compatibility chosen and the target_info supplied by the
        CHALLENGE_MESSAGE. It is quite different from what is set in the
        document as it combines the NTLMv1, NTLM2 and NTLMv2 methods into one
        and calls separate methods based on the ntlm_compatibility flag chosen.

        :return: response (LmChallengeResponse) - The LM response to the server
            challenge. Computed by the client
        """
        if self._negotiate_flags & \
                NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY and \
                self._ntlm_compatibility < 3:
            response = self._get_LMv1_with_session_security_response(
                self._client_challenge
            )
        elif 0 <= self._ntlm_compatibility <= 1:
            response = self._get_LMv1_response(self._password,
                                               self._server_challenge)
        elif self._ntlm_compatibility == 2:
            # Based on the compatibility level we don't want to use LM
            # responses, ignore the session_base_key as it is returned in nt
            response, ignore_key = \
                self._get_NTLMv1_response(self._password,
                                          self._server_challenge)
        else:
            """
            [MS-NLMP] v28.0 page 45 - 2016-07-14

            3.1.5.12 Client Received a CHALLENGE_MESSAGE from the Server
            If NTLMv2 authentication is used and the CHALLENGE_MESSAGE
            TargetInfo field has an MsvAvTimestamp present, the client SHOULD
            NOT send the LmChallengeResponse and SHOULD send Z(24) instead.
            """
            response = self._get_LMv2_response(self._user_name, self._password,
                                               self._domain_name,
                                               self._server_challenge,
                                               self._client_challenge)
            if self._server_target_info is not None:
                timestamp = \
                    self._server_target_info[AvId.MSV_AV_TIMESTAMP]
                if timestamp is not None:
                    response = b'\x00' * 24

        return response

    def get_nt_challenge_response(self, lm_challenge_response,
                                  server_certificate_hash=None, cbt_data=None):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.3.1 - NTLM v1 Authentication
        3.3.2 - NTLM v2 Authentication

        This method returns the NtChallengeResponse key based on the
        ntlm_compatibility chosen and the target_info supplied by the
        CHALLENGE_MESSAGE. It is quite different from what is set in the
        document as it combines the NTLMv1, NTLM2 and NTLMv2 methods into one
        and calls separate methods based on the ntlm_compatibility value
        chosen.

        :param lm_challenge_response: The LmChallengeResponse calculated
            beforehand, used to get the key_exchange_key value
        :param server_certificate_hash: This is deprecated and will be removed
            in a future version, use cbt_data instead
        :param cbt_data: The GssChannelBindingsStruct to bind in the NTLM
            response
        :return response: (NtChallengeResponse) - The NT response to the server
            challenge. Computed by the client
        :return session_base_key: (SessionBaseKey) - A session key calculated
            from the user password challenge
        :return target_info: (AV_PAIR) - The AV_PAIR structure used in the
            nt_challenge calculations
        """
        if self._negotiate_flags & \
                NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY and \
                self._ntlm_compatibility < 3:
            # The compatibility level is less than 3 which means it doesn't
            # support NTLMv2 but we want extended security so use NTLM2 which
            # is different from NTLMv2
            # [MS-NLMP] - 3.3.1 NTLMv1 Authentication
            response, session_base_key = \
                self._get_NTLM2_response(self._password,
                                         self._server_challenge,
                                         self._client_challenge)
            lm_hash = comphash._lmowfv1(self._password)
            key_exchange_key = \
                compkeys._get_exchange_key_ntlm_v1(self._negotiate_flags,
                                                   session_base_key,
                                                   self._server_challenge,
                                                   lm_challenge_response,
                                                   lm_hash)
            target_info = None

        elif 0 <= self._ntlm_compatibility < 3:
            response, session_base_key = \
                self._get_NTLMv1_response(self._password,
                                          self._server_challenge)

            lm_hash = comphash._lmowfv1(self._password)
            key_exchange_key = \
                compkeys._get_exchange_key_ntlm_v1(self._negotiate_flags,
                                                   session_base_key,
                                                   self._server_challenge,
                                                   lm_challenge_response,
                                                   lm_hash)
            target_info = None

        else:
            if self._server_target_info is None:
                target_info = ntlm_auth.messages.TargetInfo()
            else:
                target_info = self._server_target_info

            if target_info[AvId.MSV_AV_TIMESTAMP] is None:
                timestamp = get_windows_timestamp()
            else:
                timestamp = target_info[AvId.MSV_AV_TIMESTAMP]

                # [MS-NLMP] If the CHALLENGE_MESSAGE TargetInfo field has an
                # MsvAvTimestamp present, the client SHOULD provide a MIC
                target_info[AvId.MSV_AV_FLAGS] = \
                    struct.pack("<L", AvFlags.MIC_PROVIDED)

            if server_certificate_hash is not None and cbt_data is None:
                # Older method of creating CBT struct based on the cert hash.
                # This should be avoided in favour of an explicit
                # GssChannelBindingStruct being passed in.
                certificate_digest = base64.b16decode(server_certificate_hash)

                cbt_data = GssChannelBindingsStruct()
                cbt_data[cbt_data.APPLICATION_DATA] = \
                    b'tls-server-end-point:' + certificate_digest

            if cbt_data is not None:
                cbt_bytes = cbt_data.get_data()
                cbt_hash = hashlib.md5(cbt_bytes).digest()
                target_info[AvId.MSV_AV_CHANNEL_BINDINGS] = cbt_hash

            response, session_base_key = \
                self._get_NTLMv2_response(self._user_name, self._password,
                                          self._domain_name,
                                          self._server_challenge,
                                          self._client_challenge,
                                          timestamp, target_info)

            key_exchange_key = \
                compkeys._get_exchange_key_ntlm_v2(session_base_key)

        return response, key_exchange_key, target_info

    @staticmethod
    def _get_LMv1_response(password, server_challenge):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.3 LM_RESPONSE
        The LM_RESPONSE structure defines the NTLM v1 authentication
        LmChallengeResponse in the AUTHENTICATE_MESSAGE. This response is used
        only when NTLM v1 authentication is configured.

        :param password: The password of the user we are trying to authenticate
            with
        :param server_challenge: A random 8-byte response generated by the
            server in the CHALLENGE_MESSAGE
        :return response: LmChallengeResponse to the server challenge
        """
        lm_hash = comphash._lmowfv1(password)
        response = ComputeResponse._calc_resp(lm_hash, server_challenge)

        return response

    @staticmethod
    def _get_LMv1_with_session_security_response(client_challenge):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.3 LM_RESPONSE
        The LM_RESPONSE structure defines the NTLM v1 authentication
        LmChallengeResponse in the AUTHENTICATE_MESSAGE. This response is used
        only when NTLM v1 authentication is configured and
        NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY is flages.

        :param client_challenge: A random 8-byte response generated by the
            client for the AUTHENTICATE_MESSAGE
        :return response: LmChallengeResponse to the server challenge
        """

        response = client_challenge + b'\x00' * 16

        return response

    @staticmethod
    def _get_LMv2_response(user_name, password, domain_name, server_challenge,
                           client_challenge):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.4 LMv2_RESPONSE
        The LMv2_RESPONSE structure defines the NTLM v2 authentication
        LmChallengeResponse in the AUTHENTICATE_MESSAGE. This response is used
        only when NTLM v2 authentication is configured.

        :param user_name: The user name of the user we are trying to
            authenticate with
        :param password: The password of the user we are trying to authenticate
            with
        :param domain_name: The domain name of the user account we are
            authenticated with
        :param server_challenge: A random 8-byte response generated by the
            server in the CHALLENGE_MESSAGE
        :param client_challenge: A random 8-byte response generated by the
            client for the AUTHENTICATE_MESSAGE
        :return response: LmChallengeResponse to the server challenge
        """
        nt_hash = comphash._ntowfv2(user_name, password, domain_name)
        challenge = server_challenge + client_challenge
        lm_hash = hmac.new(nt_hash, challenge, digestmod=hashlib.md5).digest()
        response = lm_hash + client_challenge

        return response

    @staticmethod
    def _get_NTLMv1_response(password, server_challenge):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.6 NTLM v1 Response: NTLM_RESPONSE
        The NTLM_RESPONSE strucutre defines the NTLM v1 authentication
        NtChallengeResponse in the AUTHENTICATE_MESSAGE. This response is only
        used when NTLM v1 authentication is configured.

        :param password: The password of the user we are trying to authenticate
            with
        :param server_challenge: A random 8-byte response generated by the
            server in the CHALLENGE_MESSAGE
        :return response: NtChallengeResponse to the server_challenge
        :return session_base_key: A session key calculated from the user
            password challenge
        """
        ntlm_hash = comphash._ntowfv1(password)
        response = ComputeResponse._calc_resp(ntlm_hash, server_challenge)

        session_base_key = hashlib.new('md4', ntlm_hash).digest()

        return response, session_base_key

    @staticmethod
    def _get_NTLM2_response(password, server_challenge, client_challenge):
        """
        [MS-NLMP] v28.0 2016-07-14

        This name is really misleading as it isn't NTLM v2 authentication
        rather this authentication is only used when the ntlm_compatibility
        level is set to a value < 3 (No NTLMv2 auth) but the
        NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY flag is set in the negotiate
        flags section. The documentation for computing this value is on page 56
        under section 3.3.1 NTLM v1 Authentication

        :param password: The password of the user we are trying to authenticate
            with
        :param server_challenge: A random 8-byte response generated by the
            server in the CHALLENGE_MESSAGE
        :param client_challenge: A random 8-byte response generated by the
            client for the AUTHENTICATE_MESSAGE
        :return response: NtChallengeResponse to the server_challenge
        :return session_base_key: A session key calculated from the user
            password challenge
        """
        ntlm_hash = comphash._ntowfv1(password)
        challenge = server_challenge + client_challenge
        nt_session_hash = hashlib.md5(challenge).digest()[:8]
        response = ComputeResponse._calc_resp(ntlm_hash, nt_session_hash[0:8])

        session_base_key = hashlib.new('md4', ntlm_hash).digest()

        return response, session_base_key

    @staticmethod
    def _get_NTLMv2_response(user_name, password, domain_name,
                             server_challenge, client_challenge, timestamp,
                             target_info):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.8 NTLM V2 Response: NTLMv2_RESPONSE
        The NTLMv2_RESPONSE strucutre defines the NTLMv2 authentication
        NtChallengeResponse in the AUTHENTICATE_MESSAGE. This response is used
        only when NTLMv2 authentication is configured.

        The guide on how this is computed is in 3.3.2 NTLM v2 Authentication.

        :param user_name: The user name of the user we are trying to
            authenticate with
        :param password: The password of the user we are trying to authenticate
            with
        :param domain_name: The domain name of the user account we are
            authenticated with
        :param server_challenge: A random 8-byte response generated by the
            server in the CHALLENGE_MESSAGE
        :param client_challenge: A random 8-byte response generated by the
            client for the AUTHENTICATE_MESSAGE
        :param timestamp: An 8-byte timestamp in windows format, 100
            nanoseconds since 1601-01-01
        :param target_info: The target_info structure from the
            CHALLENGE_MESSAGE with the CBT attached if required
        :return response: NtChallengeResponse to the server_challenge
        :return session_base_key: A session key calculated from the user
            password challenge
        """

        nt_hash = comphash._ntowfv2(user_name, password, domain_name)
        temp = ComputeResponse._get_NTLMv2_temp(timestamp, client_challenge,
                                                target_info)
        nt_proof_str = hmac.new(nt_hash,
                                (server_challenge + temp),
                                digestmod=hashlib.md5).digest()
        response = nt_proof_str + temp

        session_base_key = hmac.new(nt_hash, nt_proof_str,
                                    digestmod=hashlib.md5).digest()

        return response, session_base_key

    @staticmethod
    def _get_NTLMv2_temp(timestamp, client_challenge, target_info):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.7 NTLMv2_CLIENT_CHALLENGE - variable length
        The NTLMv2_CLIENT_CHALLENGE structure defines the client challenge in
        the AUTHENTICATE_MESSAGE. This structure is used only when NTLM v2
        authentication is configured and is transported in the NTLMv2_RESPONSE
        structure.

        The method to create this structure is defined in 3.3.2 NTLMv2
        Authentication. In this method this variable is known as the temp
        value. The target_info variable corresponds to the ServerName variable
        used in that documentation. This is in reality a lot more than just the
        ServerName and contains the AV_PAIRS structure we need to transport
        with the message like Channel Binding tokens and others. By default
        this will be the target_info returned from the CHALLENGE_MESSAGE plus
        MSV_AV_CHANNEL_BINDINGS if specified otherwise it is a new target_info
        set with MSV_AV_TIMESTAMP to the current time.

        :param timestamp: An 8-byte timestamp in windows format, 100
            nanoseconds since 1601-01-01
        :param client_challenge: A random 8-byte response generated by the
        `client for the AUTHENTICATE_MESSAGE
        :param target_info: The target_info structure from the
            CHALLENGE_MESSAGE with the CBT attached if required
        :return temp: The CLIENT_CHALLENGE structure that will be added to the
            NtChallengeResponse structure
        """
        resp_type = b'\x01'
        hi_resp_type = b'\x01'
        reserved1 = b'\x00' * 2
        reserved2 = b'\x00' * 4
        reserved3 = b'\x00' * 4
        # This byte is not in the structure defined in 2.2.2.7 but is in the
        # computation guide, works with it present
        reserved4 = b'\x00' * 4

        temp = resp_type
        temp += hi_resp_type
        temp += reserved1
        temp += reserved2
        temp += timestamp
        temp += client_challenge
        temp += reserved3
        temp += target_info.pack()
        temp += reserved4

        return temp

    @staticmethod
    def _calc_resp(password_hash, server_challenge):
        """
        Generate the LM response given a 16-byte password hash and the
        challenge from the CHALLENGE_MESSAGE

        :param password_hash: A 16-byte password hash
        :param server_challenge: A random 8-byte response generated by the
            server in the CHALLENGE_MESSAGE
        :return res: A 24-byte buffer to contain the LM response upon return
        """
        # padding with zeros to make the hash 21 bytes long
        password_hash += b'\x00' * (21 - len(password_hash))

        res = b''
        dobj = DES(DES.key56_to_key64(password_hash[0:7]))
        res = res + dobj.encrypt(server_challenge[0:8])

        dobj = DES(DES.key56_to_key64(password_hash[7:14]))
        res = res + dobj.encrypt(server_challenge[0:8])

        dobj = DES(DES.key56_to_key64(password_hash[14:21]))
        res = res + dobj.encrypt(server_challenge[0:8])
        return res


def get_windows_timestamp():
    # Get Windows Date time, 100 nanoseconds since 1601-01-01 in a 64 bit
    # structure
    seconds_since_origin = 116444736000 + calendar.timegm(time.gmtime())
    timestamp = struct.pack('<q', seconds_since_origin * 10000000)

    return timestamp
