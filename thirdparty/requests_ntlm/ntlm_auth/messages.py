# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import hashlib
import hmac
import os
import struct

from ntlm_auth.compute_response import ComputeResponse
from ntlm_auth.constants import AvId, AvFlags, MessageTypes, NegotiateFlags, \
    NTLM_SIGNATURE
from ntlm_auth.rc4 import ARC4

try:
    from collections import OrderedDict
except ImportError:  # pragma: no cover
    from ordereddict import OrderedDict


class TargetInfo(object):

    def __init__(self):
        self.fields = OrderedDict()

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, key):
        return self.fields.get(key, None)

    def __delitem__(self, key):
        del self.fields[key]

    def pack(self):
        if AvId.MSV_AV_EOL in self.fields:
            del self[AvId.MSV_AV_EOL]

        data = b''
        for attribute_type, attribute_value in self.fields.items():
            data += struct.pack("<HH", attribute_type, len(attribute_value))
            data += attribute_value

        # end with a NTLMSSP_AV_EOL
        data += struct.pack('<HH', AvId.MSV_AV_EOL, 0)
        return data

    def unpack(self, data):
        attribute_type = None
        while attribute_type != AvId.MSV_AV_EOL:
            attribute_type = struct.unpack("<H", data[:2])[0]
            attribute_length = struct.unpack("<H", data[2:4])[0]
            self[attribute_type] = data[4:attribute_length + 4]
            data = data[4 + attribute_length:]


class NegotiateMessage(object):
    EXPECTED_BODY_LENGTH = 40

    def __init__(self, negotiate_flags, domain_name, workstation):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.1.1 NEGOTIATE_MESSAGE
        The NEGOTIATE_MESSAGE defines an NTLM Negotiate message that is sent
        from the client to the server. This message allows the client to
        specify its supported NTLM options to the server.

        :param negotiate_flags: A NEGOTIATE structure that contains a set of
            bit flags. These flags are the options the client supports
        :param domain_name: The domain name of the user to authenticate with,
            default is None
        :param workstation: The worksation of the client machine, default is
            None

        Attributes:
            signature: An 8-byte character array that MUST contain the ASCII
                string 'NTLMSSP\0'
            message_type: A 32-bit unsigned integer that indicates the message
                type. This field must be set to 0x00000001
            negotiate_flags: A NEGOTIATE structure that contains a set of bit
                flags. These flags are the options the client supports
            version: Contains the windows version info of the client. It is
                used only debugging purposes and are only set when
                NTLMSSP_NEGOTIATE_VERSION flag is set
            domain_name: A byte-array that contains the name of the client
                authentication domain that MUST Be encoded in the negotiated
                character set
            workstation: A byte-array that contains the name of the client
                machine that MUST Be encoded in the negotiated character set
        """

        self.signature = NTLM_SIGNATURE
        self.message_type = struct.pack('<L', MessageTypes.NTLM_NEGOTIATE)

        # Check if the domain_name value is set, if it is, make sure the
        # negotiate_flag is also set
        if domain_name is None:
            self.domain_name = ''
        else:
            self.domain_name = domain_name
            negotiate_flags |= \
                NegotiateFlags.NTLMSSP_NEGOTIATE_OEM_DOMAIN_SUPPLIED

        # Check if the workstation value is set, if it is, make sure the
        # negotiate_flag is also set
        if workstation is None:
            self.workstation = ''
        else:
            self.workstation = workstation
            negotiate_flags |= \
                NegotiateFlags.NTLMSSP_NEGOTIATE_OEM_WORKSTATION_SUPPLIED

        # Set the encoding flag to use UNICODE, remove OEM if set.
        negotiate_flags |= NegotiateFlags.NTLMSSP_NEGOTIATE_UNICODE
        negotiate_flags &= ~NegotiateFlags.NTLMSSP_NEGOTIATE_OEM

        # The domain name and workstation are always OEM encoded.
        self.domain_name = self.domain_name.encode('ascii')
        self.workstation = self.workstation.encode('ascii')

        self.version = get_version(negotiate_flags)

        self.negotiate_flags = struct.pack('<I', negotiate_flags)

    def get_data(self):
        payload_offset = self.EXPECTED_BODY_LENGTH

        # DomainNameFields - 8 bytes
        domain_name_len = struct.pack('<H', len(self.domain_name))
        domain_name_max_len = struct.pack('<H', len(self.domain_name))
        domain_name_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.domain_name)

        # WorkstationFields - 8 bytes
        workstation_len = struct.pack('<H', len(self.workstation))
        workstation_max_len = struct.pack('<H', len(self.workstation))
        workstation_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.workstation)

        # Payload - variable length
        payload = self.domain_name
        payload += self.workstation

        # Bring the header values together into 1 message
        msg1 = self.signature
        msg1 += self.message_type
        msg1 += self.negotiate_flags
        msg1 += domain_name_len
        msg1 += domain_name_max_len
        msg1 += domain_name_buffer_offset
        msg1 += workstation_len
        msg1 += workstation_max_len
        msg1 += workstation_buffer_offset
        msg1 += self.version

        assert self.EXPECTED_BODY_LENGTH == len(msg1),\
            "BODY_LENGTH: %d != msg1: %d"\
            % (self.EXPECTED_BODY_LENGTH, len(msg1))

        # Adding the payload data to the message
        msg1 += payload
        return msg1


class ChallengeMessage(object):

    def __init__(self, msg2):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.1.2 CHALLENGE_MESSAGE
        The CHALLENGE_MESSAGE defines an NTLM challenge message that is sent
        from the server to the client. The CHALLENGE_MESSAGE is used by the
        server to challenge the client to prove its identity, For
        connection-oriented requests, the CHALLENGE_MESSAGE generated by the
        server is in response to the NEGOTIATE_MESSAGE from the client.

        :param msg2: The CHALLENGE_MESSAGE received from the server after
            sending our NEGOTIATE_MESSAGE. This has been decoded from a base64
            string

        Attributes
            signature: An 8-byte character array that MUST contain the ASCII
                string 'NTLMSSP\0'
            message_type: A 32-bit unsigned integer that indicates the message
                type. This field must be set to 0x00000002
            negotiate_flags: A NEGOTIATE strucutre that contains a set of bit
                flags. The server sets flags to indicate options it supports
            server_challenge: A 64-bit value that contains the NTLM challenge.
                The challenge is a 64-bit nonce. Used in the
                AuthenticateMessage message
            reserved: An 8-byte array whose elements MUST be zero when sent and
                MUST be ignored on receipt
            version: When NTLMSSP_NEGOTIATE_VERSION flag is set in
                negotiate_flags field which contains the windows version info.
                Used only for debugging purposes
            target_name: When NTLMSSP_REQUEST_TARGET is set is a byte array
                that contains the name of the server authentication realm. In a
                domain environment this is the domain name not server name
            target_info: When NTLMSSP_NEGOTIATE_TARGET_INFO is set is a byte
                array that contains a sequence of AV_PAIR structures
        """

        self.data = msg2
        # Setting the object values from the raw_challenge_message
        self.signature = msg2[0:8]
        self.message_type = struct.unpack("<I", msg2[8:12])[0]
        self.negotiate_flags = struct.unpack("<I", msg2[20:24])[0]
        self.server_challenge = msg2[24:32]
        self.reserved = msg2[32:40]

        if self.negotiate_flags & \
                NegotiateFlags.NTLMSSP_NEGOTIATE_VERSION and \
                self.negotiate_flags & \
                NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY and \
                len(msg2) > 48:
            self.version = struct.unpack("<q", msg2[48:56])[0]
        else:
            self.version = None

        if self.negotiate_flags & NegotiateFlags.NTLMSSP_REQUEST_TARGET:
            target_name_len = struct.unpack("<H", msg2[12:14])[0]
            target_name_max_len = struct.unpack("<H", msg2[14:16])[0]
            target_name_offset_mix = struct.unpack("<I", msg2[16:20])[0]
            target_offset_max = target_name_offset_mix + target_name_len
            self.target_name = msg2[target_name_offset_mix:target_offset_max]
        else:
            self.target_name = None

        if self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_TARGET_INFO:
            target_info_len = struct.unpack("<H", msg2[40:42])[0]
            target_info_max_len = struct.unpack("<H", msg2[42:44])[0]
            target_info_offset_min = struct.unpack("<I", msg2[44:48])[0]
            target_info_offset_max = target_info_offset_min + target_info_len

            target_info_raw = \
                msg2[target_info_offset_min:target_info_offset_max]
            self.target_info = TargetInfo()
            self.target_info.unpack(target_info_raw)
        else:
            self.target_info = None

        # Verify initial integrity of the message, it matches what should be
        # there
        assert self.signature == NTLM_SIGNATURE
        assert self.message_type == MessageTypes.NTLM_CHALLENGE

    def get_data(self):
        return self.data


class AuthenticateMessage(object):
    EXPECTED_BODY_LENGTH = 72
    EXPECTED_BODY_LENGTH_WITH_MIC = 88

    def __init__(self, user_name, password, domain_name, workstation,
                 challenge_message, ntlm_compatibility,
                 server_certificate_hash=None, cbt_data=None):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.1.3 AUTHENTICATE_MESSAGE
        The AUTHENTICATE_MESSAGE defines an NTLM authenticate message that is
        sent from the client to the server after the CHALLENGE_MESSAGE is
        processed by the client.

        :param user_name: The user name of the user we are trying to
            authenticate with
        :param password: The password of the user we are trying to authenticate
            with
        :param domain_name: The domain name of the user account we are
            authenticated with, default is None
        :param workstation: The workstation we are using to authenticate with,
            default is None
        :param challenge_message: A ChallengeMessage object that was received
            from the server after the negotiate_message
        :param ntlm_compatibility: The Lan Manager Compatibility Level, used to
            determine what NTLM auth version to use, see Ntlm in ntlm.py for
            more details
        :param server_certificate_hash: Deprecated, used cbt_data instead
        :param cbt_data: The GssChannelBindingsStruct that contains the CBT
            data to bind in the auth response

        Message Attributes (Attributes used to compute the message structure):
            signature: An 8-byte character array that MUST contain the ASCII
                string 'NTLMSSP\0'
            message_type: A 32-bit unsigned integer that indicates the message
                type. This field must be set to 0x00000003
            negotiate_flags: A NEGOTIATE strucutre that contains a set of bit
                flags. These flags are the choices the client has made from the
                CHALLENGE_MESSAGE options
            version: Contains the windows version info of the client. It is
                used only debugging purposes and are only set when
                NTLMSSP_NEGOTIATE_VERSION flag is set
            mic: The message integrity for the NEGOTIATE_MESSAGE,
                CHALLENGE_MESSAGE and AUTHENTICATE_MESSAGE
            lm_challenge_response: An LM_RESPONSE of LMv2_RESPONSE structure
                that contains the computed LM response to the challenge
            nt_challenge_response: An NTLM_RESPONSE or NTLMv2_RESPONSE
                structure that contains the computed NT response to the
                challenge
            domain_name: The domain or computer name hosting the user account,
                MUST be encoded in the negotiated character set
            user_name: The name of the user to be authenticated, MUST be
                encoded in the negotiated character set
            workstation: The name of the computer to which the user is logged
                on, MUST Be encoded in the negotiated character set
            encrypted_random_session_key: The client's encrypted random session
                key

        Non-Message Attributes (Attributes not used in auth message):
            exported_session_key: A randomly generated session key based on
                other keys, used to derive the SIGNKEY and SEALKEY
            target_info: The AV_PAIR structure used in the nt response
                calculation
        """
        self.signature = NTLM_SIGNATURE
        self.message_type = struct.pack('<L', MessageTypes.NTLM_AUTHENTICATE)
        self.negotiate_flags = challenge_message.negotiate_flags
        self.version = get_version(self.negotiate_flags)
        self.mic = None

        if domain_name is None:
            self.domain_name = ''
        else:
            self.domain_name = domain_name

        if workstation is None:
            self.workstation = ''
        else:
            self.workstation = workstation

        if self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_UNICODE:
            self.negotiate_flags &= ~NegotiateFlags.NTLMSSP_NEGOTIATE_OEM
            encoding_value = 'utf-16-le'
        else:
            encoding_value = 'ascii'

        self.domain_name = self.domain_name.encode(encoding_value)
        self.user_name = user_name.encode(encoding_value)
        self.workstation = self.workstation.encode(encoding_value)

        compute_response = ComputeResponse(user_name, password, domain_name,
                                           challenge_message,
                                           ntlm_compatibility)

        self.lm_challenge_response = \
            compute_response.get_lm_challenge_response()
        self.nt_challenge_response, key_exchange_key, target_info = \
            compute_response.get_nt_challenge_response(
                self.lm_challenge_response, server_certificate_hash, cbt_data)
        self.target_info = target_info

        if self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_KEY_EXCH:
            self.exported_session_key = get_random_export_session_key()

            rc4_handle = ARC4(key_exchange_key)
            self.encrypted_random_session_key = \
                rc4_handle.update(self.exported_session_key)
        else:
            self.exported_session_key = key_exchange_key
            self.encrypted_random_session_key = b''

        self.negotiate_flags = struct.pack('<I', self.negotiate_flags)

    def get_data(self):
        if self.mic is None:
            mic = b''
            expected_body_length = self.EXPECTED_BODY_LENGTH
        else:
            mic = self.mic
            expected_body_length = self.EXPECTED_BODY_LENGTH_WITH_MIC

        payload_offset = expected_body_length

        # DomainNameFields - 8 bytes
        domain_name_len = struct.pack('<H', len(self.domain_name))
        domain_name_max_len = struct.pack('<H', len(self.domain_name))
        domain_name_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.domain_name)

        # UserNameFields - 8 bytes
        user_name_len = struct.pack('<H', len(self.user_name))
        user_name_max_len = struct.pack('<H', len(self.user_name))
        user_name_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.user_name)

        # WorkstatonFields - 8 bytes
        workstation_len = struct.pack('<H', len(self.workstation))
        workstation_max_len = struct.pack('<H', len(self.workstation))
        workstation_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.workstation)

        # LmChallengeResponseFields - 8 bytes
        lm_challenge_response_len = \
            struct.pack('<H', len(self.lm_challenge_response))
        lm_challenge_response_max_len = \
            struct.pack('<H', len(self.lm_challenge_response))
        lm_challenge_response_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.lm_challenge_response)

        # NtChallengeResponseFields - 8 bytes
        nt_challenge_response_len = \
            struct.pack('<H', len(self.nt_challenge_response))
        nt_challenge_response_max_len = \
            struct.pack('<H', len(self.nt_challenge_response))
        nt_challenge_response_buffer_offset = struct.pack('<I', payload_offset)
        payload_offset += len(self.nt_challenge_response)

        # EncryptedRandomSessionKeyFields - 8 bytes
        encrypted_random_session_key_len = \
            struct.pack('<H', len(self.encrypted_random_session_key))
        encrypted_random_session_key_max_len = \
            struct.pack('<H', len(self.encrypted_random_session_key))
        encrypted_random_session_key_buffer_offset = \
            struct.pack('<I', payload_offset)
        payload_offset += len(self.encrypted_random_session_key)

        # Payload - variable length
        payload = self.domain_name
        payload += self.user_name
        payload += self.workstation
        payload += self.lm_challenge_response
        payload += self.nt_challenge_response
        payload += self.encrypted_random_session_key

        msg3 = self.signature
        msg3 += self.message_type
        msg3 += lm_challenge_response_len
        msg3 += lm_challenge_response_max_len
        msg3 += lm_challenge_response_buffer_offset
        msg3 += nt_challenge_response_len
        msg3 += nt_challenge_response_max_len
        msg3 += nt_challenge_response_buffer_offset
        msg3 += domain_name_len
        msg3 += domain_name_max_len
        msg3 += domain_name_buffer_offset
        msg3 += user_name_len
        msg3 += user_name_max_len
        msg3 += user_name_buffer_offset
        msg3 += workstation_len
        msg3 += workstation_max_len
        msg3 += workstation_buffer_offset
        msg3 += encrypted_random_session_key_len
        msg3 += encrypted_random_session_key_max_len
        msg3 += encrypted_random_session_key_buffer_offset
        msg3 += self.negotiate_flags
        msg3 += self.version
        msg3 += mic

        # Adding the payload data to the message
        msg3 += payload

        return msg3

    def add_mic(self, negotiate_message, challenge_message):
        if self.target_info is not None:
            av_flags = self.target_info[AvId.MSV_AV_FLAGS]

            if av_flags is not None and av_flags == \
                    struct.pack("<L", AvFlags.MIC_PROVIDED):
                self.mic = struct.pack("<IIII", 0, 0, 0, 0)
                negotiate_data = negotiate_message.get_data()
                challenge_data = challenge_message.get_data()
                authenticate_data = self.get_data()

                hmac_data = negotiate_data + challenge_data + authenticate_data
                mic = hmac.new(self.exported_session_key, hmac_data,
                               digestmod=hashlib.md5).digest()
                self.mic = mic


def get_version(negotiate_flags):
    # Check the negotiate_flag version is set, if it is make sure the version
    # info is added to the data
    if negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_VERSION:
        # TODO: Get the major and minor version of Windows instead of using
        # default values
        product_major_version = struct.pack('<B', 6)
        product_minor_version = struct.pack('<B', 1)
        product_build = struct.pack('<H', 7601)
        version_reserved = b'\x00' * 3
        ntlm_revision_current = struct.pack('<B', 15)
        version = product_major_version
        version += product_minor_version
        version += product_build
        version += version_reserved
        version += ntlm_revision_current
    else:
        version = b'\x00' * 8

    return version


def get_random_export_session_key():
    return os.urandom(16)
