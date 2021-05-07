# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import struct


# lots of help from
# http://page.math.tu-berlin.de/~kant/teaching/hess/krypto-ws2006/des.htm
class DES(object):

    # first table used to derive the sub keys
    _pc1 = [
        56, 48, 40, 32, 24, 16, 8,
        0, 57, 49, 41, 33, 25, 17,
        9, 1, 58, 50, 42, 34, 26,
        18, 10, 2, 59, 51, 43, 35,
        62, 54, 46, 38, 30, 22, 14,
        6, 61, 53, 45, 37, 29, 21,
        13, 5, 60, 52, 44, 36, 28,
        20, 12, 4, 27, 19, 11, 3
    ]

    # shifts the sub key from pc1 to calculate the 16 sub keys
    _shift_indexes = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]

    # second table used to derive the sub keys
    _pc2 = [
        13, 16, 10, 23, 0, 4,
        2, 27, 14, 5, 20, 9,
        22, 18, 11, 3, 25, 7,
        15, 6, 26, 19, 12, 1,
        40, 51, 30, 36, 46, 54,
        29, 39, 50, 44, 32, 47,
        43, 48, 38, 55, 33, 52,
        45, 41, 49, 35, 28, 31
    ]

    # initial permutation of the 64-bits of the message data
    _ip = [
        57, 49, 41, 33, 25, 17, 9, 1,
        59, 51, 43, 35, 27, 19, 11, 3,
        61, 53, 45, 37, 29, 21, 13, 5,
        63, 55, 47, 39, 31, 23, 15, 7,
        56, 48, 40, 32, 24, 16, 8, 0,
        58, 50, 42, 34, 26, 18, 10, 2,
        60, 52, 44, 36, 28, 20, 12, 4,
        62, 54, 46, 38, 30, 22, 14, 6
    ]

    # used to expand the each initial permuted half into a 48-bit values
    _e_bit_selection = [
        31, 0, 1, 2, 3, 4,
        3, 4, 5, 6, 7, 8,
        7, 8, 9, 10, 11, 12,
        11, 12, 13, 14, 15, 16,
        15, 16, 17, 18, 19, 20,
        19, 20, 21, 22, 23, 24,
        23, 24, 25, 26, 27, 28,
        27, 28, 29, 30, 31, 0
    ]

    # list of boxes used in the encryption process
    _s_boxes = [
        [
            14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7,
            0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
            4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0,
            15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13
        ],
        [
            15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10,
            3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
            0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15,
            13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9
        ],
        [
            10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8,
            13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
            13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7,
            1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12
        ],
        [
            7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15,
            13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
            10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4,
            3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14
        ],
        [
            2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9,
            14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
            4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14,
            11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3
        ],
        [
            12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11,
            10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
            9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6,
            4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13
        ],
        [
            4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1,
            13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
            1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2,
            6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12
        ],
        [
            13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7,
            1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
            7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8,
            2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11
        ]
    ]

    # converts the s-box permutation one more time
    _p = [
        15, 6, 19, 20, 28, 11,
        27, 16, 0, 14, 22, 25,
        4, 17, 30, 9, 1, 7,
        23, 13, 31, 26, 2, 8,
        18, 12, 29, 5, 21, 10,
        3, 24
    ]

    # final permutation of the message
    _final_ip = [
        39, 7, 47, 15, 55, 23, 63, 31,
        38, 6, 46, 14, 54, 22, 62, 30,
        37, 5, 45, 13, 53, 21, 61, 29,
        36, 4, 44, 12, 52, 20, 60, 28,
        35, 3, 43, 11, 51, 19, 59, 27,
        34, 2, 42, 10, 50, 18, 58, 26,
        33, 1, 41, 9, 49, 17, 57, 25,
        32, 0, 40, 8, 48, 16, 56, 24
    ]

    def __init__(self, key):
        """
        Creates a DES cipher class with the key initialised. This key must be
        8 bytes in length. This only supports the ECB cipher mode as that is
        what is used in the LM hash calculation.

        :param key: The 8-byte key to use in the Cipher
        """
        if len(key) != 8:
            raise ValueError("DES encryption key should be 8 bytes in length")

        self.key = key
        self._subkeys = self._create_subkeys(self.key)

    def encrypt(self, data, pad=True):
        """
        DES encrypts the data based on the key it was initialised with.

        :param data: The bytes string to encrypt
        :param pad: Whether to right pad data with \x00 to a multiple of 8
        :return: The encrypted bytes string
        """
        encrypted_data = b""
        for i in range(0, len(data), 8):
            block = data[i:i + 8]
            block_length = len(block)
            if block_length != 8 and pad:
                block += b"\x00" * (8 - block_length)
            elif block_length != 8:
                raise ValueError("DES encryption must be a multiple of 8 "
                                 "bytes")
            encrypted_data += self._encode_block(block)

        return encrypted_data

    def decrypt(self, data):
        """
        DES decrypts the data based on the key it was initialised with.

        :param data: The encrypted bytes string to decrypt
        :return: The decrypted bytes string
        """
        decrypted_data = b""
        for i in range(0, len(data), 8):
            block = data[i:i + 8]
            block_length = len(block)
            if block_length != 8:
                raise ValueError("DES decryption must be a multiple of 8 "
                                 "bytes")

            decrypted_data += self._decode_block(block)

        return decrypted_data

    @staticmethod
    def key56_to_key64(key):
        """
        This takes in an a bytes string of 7 bytes and converts it to a bytes
        string of 8 bytes with the odd parity bit being set to every 8 bits,

        For example

        b"\x01\x02\x03\x04\x05\x06\x07"
        00000001 00000010 00000011 00000100 00000101 00000110 00000111

        is converted to

        b"\x01\x80\x80\x61\x40\x29\x19\x0E"
        00000001 10000000 10000000 01100001 01000000 00101001 00011001 00001110

        https://crypto.stackexchange.com/questions/15799/des-with-actual-7-byte-key

        :param key: 7-byte string sized key
        :return: 8-byte string with the parity bits sets from the 7-byte string
        """
        if len(key) != 7:
            raise ValueError("DES 7-byte key is not 7 bytes in length, "
                             "actual: %d" % len(key))

        new_key = b""
        for i in range(0, 8):
            if i == 0:
                new_value = struct.unpack("B", key[i:i+1])[0]
            elif i == 7:
                new_value = struct.unpack("B", key[6:7])[0]
                new_value = (new_value << 1) & 0xFF
            else:
                new_value = struct.unpack("B", key[i - 1:i])[0]
                next_value = struct.unpack("B", key[i:i + 1])[0]
                new_value = ((new_value << (8 - i)) & 0xFF) | next_value >> i

            # clear the last bit so the count isn't off
            new_value = new_value & ~(1 << 0)

            # set the last bit if the number of set bits are even
            new_value = new_value | int(not DES.bit_count(new_value) & 0x1)
            new_key += struct.pack("B", new_value)

        return new_key

    @staticmethod
    def bit_count(i):
        # counts the number of bits that are 1 in the integer
        count = 0
        while i:
            i &= i - 1
            count += 1

        return count

    def _create_subkeys(self, key):
        # convert the key into a list of bits
        key_bits = self._get_bits(key)

        # reorder the bits based on the pc1 table
        pc1_bits = [key_bits[x] for x in self._pc1]

        # split the table into 2 and append to the first entry
        c = [pc1_bits[0:28]]
        d = [pc1_bits[28:56]]

        # now populate the remaining blocks by shifting the values
        for i, shift_index in enumerate(self._shift_indexes):
            c.append(self._shift_bits(c[i], shift_index))
            d.append(self._shift_bits(d[i], shift_index))

        subkeys = list()
        for i in range(1, 17):
            cd = c[i] + d[i]
            subkey_bits = [cd[x] for x in self._pc2]
            subkeys.append(subkey_bits)

        return subkeys

    def _shift_bits(self, bits, shifts):
        new_bits = [None] * 28
        for i in range(28):
            shift_index = i + shifts
            if shift_index >= 28:
                shift_index = shift_index - 28
            new_bits[i] = bits[shift_index]

        return new_bits

    def _get_bits(self, data):
        bits = []
        for i in range(len(data)):
            b = struct.unpack("B", data[i:i + 1])[0]
            bits.append(1 if b & 0x80 else 0)
            bits.append(1 if b & 0x40 else 0)
            bits.append(1 if b & 0x20 else 0)
            bits.append(1 if b & 0x10 else 0)
            bits.append(1 if b & 0x08 else 0)
            bits.append(1 if b & 0x04 else 0)
            bits.append(1 if b & 0x02 else 0)
            bits.append(1 if b & 0x01 else 0)
        return bits

    def _encode_block(self, block):
        block_bits = self._get_bits(block)
        lr = [block_bits[x] for x in self._ip]

        l = [lr[0:32]]
        r = [lr[32:64]]
        for i in range(16):
            computed_block = self._compute_block(r[i], self._subkeys[i])
            new_r = [int(computed_block[k] != l[i][k]) for k in range(32)]

            l.append(r[i])
            r.append(new_r)

        # apply the final permutation on the l and r bits backwards
        rl = r[16] + l[16]
        encrypted_bits = [rl[x] for x in self._final_ip]
        encrypted_bytes = b""
        for i in range(0, 64, 8):
            i_byte = int("".join([str(x) for x in encrypted_bits[i:i + 8]]), 2)
            encrypted_bytes += struct.pack("B", i_byte)

        return encrypted_bytes

    def _decode_block(self, block):
        block_bits = self._get_bits(block)
        rl = [None] * 64
        for i, idx in enumerate(self._final_ip):
            rl[idx] = block_bits[i]

        r = [None] * 17
        l = [None] * 17
        r[16] = rl[0:32]
        l[16] = rl[32:64]
        for i in range(15, -1, -1):
            computed_block = self._compute_block(l[i + 1], self._subkeys[i])
            new_l = [int(computed_block[k] != r[i + 1][k]) for k in range(32)]
            r[i] = l[i + 1]
            l[i] = new_l

        lr = l[0] + r[0]
        decrypted_bits = [None] * 64
        for i, idx in enumerate(self._ip):
            decrypted_bits[idx] = lr[i]

        decrypted_bytes = b""
        for i in range(0, 64, 8):
            i_byte = int("".join([str(x) for x in decrypted_bits[i:i + 8]]), 2)
            decrypted_bytes += struct.pack("B", i_byte)

        return decrypted_bytes

    def _compute_block(self, block, key):
        expanded_block = [block[x] for x in self._e_bit_selection]
        new_block = [int(key[i] != expanded_block[i]) for i in range(48)]

        # calculate with the s-boxes
        s_box_perm = []
        s_box_iter = 0
        # now go through each block (8 groups of 6 bits) and run the s-boxes
        for i in range(0, 48, 6):
            current_block = new_block[i:i + 6]
            row_bits = [str(current_block[0]), str(current_block[-1])]
            column_bits = [str(x) for x in current_block[1:-1]]

            s_box_row = int("".join(row_bits), 2)
            s_box_column = int("".join(column_bits), 2)
            s_box_address = (s_box_row * 16) + s_box_column
            s_box_value = self._s_boxes[s_box_iter][s_box_address]
            s_box_iter += 1

            s_box_perm.append(1 if s_box_value & 0x8 else 0)
            s_box_perm.append(1 if s_box_value & 0x4 else 0)
            s_box_perm.append(1 if s_box_value & 0x2 else 0)
            s_box_perm.append(1 if s_box_value & 0x1 else 0)

        final_block = [s_box_perm[x] for x in self._p]
        return final_block
