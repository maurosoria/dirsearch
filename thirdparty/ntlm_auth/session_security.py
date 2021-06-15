# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import binascii
import hashlib
import hmac
import struct

import thirdparty.ntlm_auth.compute_keys as compkeys

from thirdparty.ntlm_auth.constants import NegotiateFlags, SignSealConstants
from thirdparty.ntlm_auth.rc4 import ARC4


class _NtlmMessageSignature1(object):
    EXPECTED_BODY_LENGTH = 16

    def __init__(self, random_pad, checksum, seq_num):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.9.1 NTLMSSP_MESSAGE_SIGNATURE
        This version of the NTLMSSP_MESSAGE_SIGNATURE structure MUST be used
        when the NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY flag is not
        negotiated.

        :param random_pad: A 4-byte array that contains the random pad for the
            message
        :param checksum: A 4-byte array that contains the checksum for the
            message
        :param seq_num: A 32-bit unsigned integer that contains the NTLM
            sequence number for this application message
        """
        self.version = b"\x01\x00\x00\x00"
        self.random_pad = random_pad
        self.checksum = checksum
        self.seq_num = seq_num

    def get_data(self):
        signature = self.version
        signature += self.random_pad
        signature += self.checksum
        signature += self.seq_num

        assert self.EXPECTED_BODY_LENGTH == len(signature), \
            "BODY_LENGTH: %d != signature: %d" \
            % (self.EXPECTED_BODY_LENGTH, len(signature))

        return signature


class _NtlmMessageSignature2(object):
    EXPECTED_BODY_LENGTH = 16

    def __init__(self, checksum, seq_num):
        """
        [MS-NLMP] v28.0 2016-07-14

        2.2.2.9.2 NTLMSSP_MESSAGE_SIGNATURE for Extended Session Security
        This version of the NTLMSSP_MESSAGE_SIGNATURE structure MUST be used
        when the NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY flag is negotiated

        :param checksum: An 8-byte array that contains the checksum for the
            message
        :param seq_num: A 32-bit unsigned integer that contains the NTLM
            sequence number for this application message
        """
        self.version = b"\x01\x00\x00\x00"
        self.checksum = checksum
        self.seq_num = seq_num

    def get_data(self):
        signature = self.version
        signature += self.checksum
        signature += self.seq_num

        assert self.EXPECTED_BODY_LENGTH == len(signature),\
            "BODY_LENGTH: %d != signature: %d"\
            % (self.EXPECTED_BODY_LENGTH, len(signature))

        return signature


class SessionSecurity(object):

    def __init__(self, negotiate_flags, exported_session_key, source="client"):
        """
        Initialises a security session context that can be used by libraries
        that call ntlm-auth to sign and seal messages send to the server as
        well as verify and unseal messages that have been received from the
        server. This is similar to the GSS_Wrap functions specified in the
        MS-NLMP document which does the same task.

        :param negotiate_flags: The negotiate flag structure that has been
            negotiated with the server
        :param exported_session_key: A 128-bit session key used to derive
            signing and sealing keys
        :param source: The source of the message, only used in test scenarios
            when testing out a server sealing and unsealing
        """
        self.negotiate_flags = negotiate_flags
        self.exported_session_key = exported_session_key
        self.outgoing_seq_num = 0
        self.incoming_seq_num = 0
        self._source = source
        self._client_sealing_key = compkeys.get_seal_key(self.negotiate_flags, exported_session_key,
                                                         SignSealConstants.CLIENT_SEALING)
        self._server_sealing_key = compkeys.get_seal_key(self.negotiate_flags, exported_session_key,
                                                         SignSealConstants.SERVER_SEALING)

        self.outgoing_handle = None
        self.incoming_handle = None
        self.reset_rc4_state(True)
        self.reset_rc4_state(False)

        if source == "client":
            self.outgoing_signing_key = compkeys.get_sign_key(exported_session_key, SignSealConstants.CLIENT_SIGNING)
            self.incoming_signing_key = compkeys.get_sign_key(exported_session_key, SignSealConstants.SERVER_SIGNING)
        elif source == "server":
            self.outgoing_signing_key = compkeys.get_sign_key(exported_session_key, SignSealConstants.SERVER_SIGNING)
            self.incoming_signing_key = compkeys.get_sign_key(exported_session_key, SignSealConstants.CLIENT_SIGNING)
        else:
            raise ValueError("Invalid source parameter %s, must be client "
                             "or server" % source)

    def reset_rc4_state(self, outgoing=True):
        csk = self._client_sealing_key
        ssk = self._server_sealing_key
        if outgoing:
            self.outgoing_handle = ARC4(csk if self._source == 'client' else ssk)
        else:
            self.incoming_handle = ARC4(ssk if self._source == 'client' else csk)

    def wrap(self, message):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.4.6 GSS_WrapEx()
        Emulates the GSS_Wrap() implementation to sign and seal messages if the
        correct flags are set.

        :param message: The message data that will be wrapped
        :return message: The message that has been sealed if flags are set
        :return signature: The signature of the message, None if flags are not
            set
        """
        if self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_SEAL:
            encrypted_message = self._seal_message(message)
            signature = self.get_signature(message)
            message = encrypted_message

        elif self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_SIGN:
            signature = self.get_signature(message)
        else:
            signature = None

        return message, signature

    def unwrap(self, message, signature):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.4.7 GSS_UnwrapEx()
        Emulates the GSS_Unwrap() implementation to unseal messages and verify
        the signature sent matches what has been computed locally. Will throw
        an Exception if the signature doesn't match

        :param message: The message data received from the server
        :param signature: The signature of the message
        :return message: The message that has been unsealed if flags are set
        """
        if self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_SEAL:
            message = self._unseal_message(message)
            self.verify_signature(message, signature)

        elif self.negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_SIGN:
            self.verify_signature(message, signature)

        return message

    def _seal_message(self, message):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.4.3 Message Confidentiality
        Will generate an encrypted message using RC4 based on the
        ClientSealingKey

        :param message: The message to be sealed (encrypted)
        :return encrypted_message: The encrypted message
        """
        encrypted_message = self.outgoing_handle.update(message)
        return encrypted_message

    def _unseal_message(self, message):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.4.3 Message Confidentiality
        Will generate a dencrypted message using RC4 based on the
        ServerSealingKey

        :param message: The message to be unsealed (dencrypted)
        :return decrypted_message: The decrypted message
        """
        decrypted_message = self.incoming_handle.update(message)
        return decrypted_message

    def get_signature(self, message):
        """
        [MS-NLMP] v28.0 2016-07-14

        3.4.4 Message Signature Functions
        Will create the signature based on the message to send to the server.
        Depending on the negotiate_flags set this could either be an NTLMv1
        signature or NTLMv2 with Extended Session Security signature.

        :param message: The message data that will be signed
        :return signature: Either _NtlmMessageSignature1 or
            _NtlmMessageSignature2 depending on the flags set
        """
        signature = calc_signature(message, self.negotiate_flags,
                                   self.outgoing_signing_key,
                                   self.outgoing_seq_num, self.outgoing_handle)
        self.outgoing_seq_num += 1

        return signature.get_data()

    def verify_signature(self, message, signature):
        """
        Will verify that the signature received from the server matches up with
        the expected signature computed locally. Will throw an exception if
        they do not match

        :param message: The message data that is received from the server
        :param signature: The signature of the message received from the server
        """
        if self.negotiate_flags & \
                NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY:
            actual_checksum = signature[4:12]
            actual_seq_num = struct.unpack("<I", signature[12:16])[0]
        else:
            actual_checksum = signature[8:12]
            actual_seq_num = struct.unpack("<I", signature[12:16])[0]

        expected_signature = calc_signature(message, self.negotiate_flags,
                                            self.incoming_signing_key,
                                            self.incoming_seq_num,
                                            self.incoming_handle)
        expected_checksum = expected_signature.checksum
        expected_seq_num = struct.unpack("<I", expected_signature.seq_num)[0]

        if actual_checksum != expected_checksum:
            raise Exception("The signature checksum does not match, message "
                            "has been altered")

        if actual_seq_num != expected_seq_num:
            raise Exception("The signature sequence number does not match up, "
                            "message not received in the correct sequence")

        self.incoming_seq_num += 1


def calc_signature(message, negotiate_flags, signing_key, seq_num, handle):
    seq_num = struct.pack("<I", seq_num)
    if negotiate_flags & \
            NegotiateFlags.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY:
        checksum_hmac = hmac.new(signing_key, seq_num + message,
                                 digestmod=hashlib.md5)
        if negotiate_flags & NegotiateFlags.NTLMSSP_NEGOTIATE_KEY_EXCH:
            checksum = handle.update(checksum_hmac.digest()[:8])
        else:
            checksum = checksum_hmac.digest()[:8]

        signature = _NtlmMessageSignature2(checksum, seq_num)

    else:
        message_crc = binascii.crc32(message) % (1 << 32)
        checksum = struct.pack("<I", message_crc)
        random_pad = handle.update(struct.pack("<I", 0))
        checksum = handle.update(checksum)
        seq_num = handle.update(seq_num)
        random_pad = struct.pack("<I", 0)

        signature = _NtlmMessageSignature1(random_pad, checksum, seq_num)

    return signature
