# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)


# [MS-NLMP] 2.2 Message Syntax - The signature field used in NTLM messages
NTLM_SIGNATURE = b'NTLMSSP\x00'


class MessageTypes(object):
    """
    [MS-NLMP] v28.0 2016-07-14

    2.2 Message Syntax
    The 3 message type options you can have in a message.
    """
    NTLM_NEGOTIATE = 0x1
    NTLM_CHALLENGE = 0x2
    NTLM_AUTHENTICATE = 0x3


class AvId(object):
    """
    [MS-NLMP] 2.2.2.1 AV_PAIR AvId
    https://msdn.microsoft.com/en-us/library/cc236646.aspx

    16-bit unsigned integer that defines the information type in the value
    field for an AV_PAIR.
    """
    MSV_AV_EOL = 0x00
    MSV_AV_NB_COMPUTER_NAME = 0x01
    MSV_AV_NB_DOMAIN_NAME = 0x02
    MSV_AV_DNS_COMPUTER_NAME = 0x03
    MSV_AV_DNS_DOMAIN_NAME = 0x04
    MSV_AV_DNS_TREE_NAME = 0x05
    MSV_AV_FLAGS = 0x06
    MSV_AV_TIMESTAMP = 0x07
    MSV_AV_SINGLE_HOST = 0x08
    MSV_AV_TARGET_NAME = 0x09
    MSV_AV_CHANNEL_BINDINGS = 0x0a


class AvFlags(object):
    """
    [MS-NLMP] v28.0 2016-07-14

    2.2.2.1 AV_PAIR (MsvAvFlags)
    A 32-bit value indicated server or client configuration
    """
    AUTHENTICATION_CONSTRAINED = 0x1
    MIC_PROVIDED = 0x2
    UNTRUSTED_SPN_SOURCE = 0x4


class NegotiateFlags(object):
    """
    [MS-NLMP] v28.0 2016-07-14

    2.2.2.5 NEGOTIATE
    During NTLM authentication, each of the following flags is a possible value
    of the NegotiateFlags field of the NEGOTIATE_MESSAGE, CHALLENGE_MESSAGE and
    AUTHENTICATE_MESSAGE, unless otherwise noted. These flags define client or
    server NTLM capabilities supported by the sender.
    """
    NTLMSSP_NEGOTIATE_56 = 0x80000000
    NTLMSSP_NEGOTIATE_KEY_EXCH = 0x40000000
    NTLMSSP_NEGOTIATE_128 = 0x20000000
    NTLMSSP_RESERVED_R1 = 0x10000000
    NTLMSSP_RESERVED_R2 = 0x08000000
    NTLMSSP_RESERVED_R3 = 0x04000000
    NTLMSSP_NEGOTIATE_VERSION = 0x02000000
    NTLMSSP_RESERVED_R4 = 0x01000000
    NTLMSSP_NEGOTIATE_TARGET_INFO = 0x00800000
    NTLMSSP_REQUEST_NON_NT_SESSION_KEY = 0x00400000
    NTLMSSP_RESERVED_R5 = 0x00200000
    NTLMSSP_NEGOTIATE_IDENTITY = 0x00100000
    NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY = 0x00080000
    NTLMSSP_RESERVED_R6 = 0x00040000
    NTLMSSP_TARGET_TYPE_SERVER = 0x00020000
    NTLMSSP_TARGET_TYPE_DOMAIN = 0x00010000
    NTLMSSP_NEGOTIATE_ALWAYS_SIGN = 0x00008000
    NTLMSSP_RESERVED_R7 = 0x00004000
    NTLMSSP_NEGOTIATE_OEM_WORKSTATION_SUPPLIED = 0x00002000
    NTLMSSP_NEGOTIATE_OEM_DOMAIN_SUPPLIED = 0x00001000
    NTLMSSP_ANOYNMOUS = 0x00000800
    NTLMSSP_RESERVED_R8 = 0x00000400
    NTLMSSP_NEGOTIATE_NTLM = 0x00000200
    NTLMSSP_RESERVED_R9 = 0x00000100
    NTLMSSP_NEGOTIATE_LM_KEY = 0x00000080
    NTLMSSP_NEGOTIATE_DATAGRAM = 0x00000040
    NTLMSSP_NEGOTIATE_SEAL = 0x00000020
    NTLMSSP_NEGOTIATE_SIGN = 0x00000010
    NTLMSSP_RESERVED_R10 = 0x00000008
    NTLMSSP_REQUEST_TARGET = 0x00000004
    NTLMSSP_NEGOTIATE_OEM = 0x00000002
    NTLMSSP_NEGOTIATE_UNICODE = 0x00000001


class SignSealConstants(object):
    # Magic Contants used to get the signing and sealing key for
    # Extended Session Security
    CLIENT_SIGNING = b"session key to client-to-server signing key magic " \
                     b"constant\x00"
    SERVER_SIGNING = b"session key to server-to-client signing key magic " \
                     b"constant\x00"
    CLIENT_SEALING = b"session key to client-to-server sealing key magic " \
                     b"constant\x00"
    SERVER_SEALING = b"session key to server-to-client sealing key magic " \
                     b"constant\x00"
