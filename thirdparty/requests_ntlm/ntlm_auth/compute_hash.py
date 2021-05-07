# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import binascii
import hashlib
import hmac
import re

from ntlm_auth.des import DES


def _lmowfv1(password):
    """
    [MS-NLMP] v28.0 2016-07-14

    3.3.1 NTLM v1 Authentication
    Same function as LMOWFv1 in document to create a one way hash of the
    password. Only used in NTLMv1 auth without session security

    :param password: The password or hash of the user we are trying to
        authenticate with
    :return res: A Lan Manager hash of the password supplied
    """
    # if the password is a hash, return the LM hash
    if re.match(r'^[a-fA-F\d]{32}:[a-fA-F\d]{32}$', password):
        lm_hash = binascii.unhexlify(password.split(':')[0])
        return lm_hash

    # fix the password to upper case and length to 14 bytes
    password = password.upper()
    lm_pw = password.encode('utf-8')
    padding_size = 0 if len(lm_pw) >= 14 else (14 - len(lm_pw))
    lm_pw += b"\x00" * padding_size

    # do hash
    magic_str = b"KGS!@#$%"  # page 56 in [MS-NLMP v28.0]

    res = b""
    dobj = DES(DES.key56_to_key64(lm_pw[0:7]))
    res += dobj.encrypt(magic_str)

    dobj = DES(DES.key56_to_key64(lm_pw[7:14]))
    res += dobj.encrypt(magic_str)

    return res


def _ntowfv1(password):
    """
    [MS-NLMP] v28.0 2016-07-14

    3.3.1 NTLM v1 Authentication
    Same function as NTOWFv1 in document to create a one way hash of the
    password. Only used in NTLMv1 auth without session security

    :param password: The password or hash of the user we are trying to
        authenticate with
    :return digest: An NT hash of the password supplied
    """

    # if the password is a hash, return the NT hash
    if re.match(r'^[a-fA-F\d]{32}:[a-fA-F\d]{32}$', password):
        nt_hash = binascii.unhexlify(password.split(':')[1])
        return nt_hash

    digest = hashlib.new('md4', password.encode('utf-16-le')).digest()
    return digest


def _ntowfv2(user_name, password, domain_name):
    """
    [MS-NLMP] v28.0 2016-07-14

    3.3.2 NTLM v2 Authentication
    Same function as NTOWFv2 (and LMOWFv2) in document to create a one way hash
    of the password. This combines some extra security features over the v1
    calculations used in NTLMv2 auth.

    :param user_name: The user name of the user we are trying to authenticate
        with
    :param password: The password of the user we are trying to authenticate
        with
    :param domain_name: The domain name of the user account we are
        authenticated with
    :return digest: An NT hash of the parameters supplied
    """
    digest = _ntowfv1(password)
    user = (user_name.upper() + domain_name).encode('utf-16-le')
    digest = hmac.new(digest, user, digestmod=hashlib.md5).digest()

    return digest
