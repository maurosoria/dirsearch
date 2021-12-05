# Copyright: (c) 2018, Jordan Borean (@jborean93) <jborean93@gmail.com>
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

import struct


class GssChannelBindingsStruct(object):

    INITIATOR_ADDTYPE = 'initiator_addtype'
    INITIATOR_ADDRESS_LENGTH = 'initiator_address_length'
    ACCEPTOR_ADDRTYPE = 'acceptor_addrtype'
    ACCEPTOR_ADDRESS_LENGTH = 'acceptor_address_length'
    APPLICATION_DATA_LENGTH = 'application_data_length'
    INITIATOR_ADDRESS = 'initiator_address'
    ACCEPTOR_ADDRESS = 'acceptor_address'
    APPLICATION_DATA = 'application_data'

    def __init__(self):
        """
        Used to send the out of band channel info as part of the authentication
        process. This is used as a way of verifying the target is who it says
        it is as this information is provided by the higher layer. In most
        cases, the CBT is just the hash of the server's TLS certificate to the
        application_data field.

        This bytes string of the packed structure is then MD5 hashed and
        included in the NTv2 response.
        """
        self.fields = {
            self.INITIATOR_ADDTYPE: 0,
            self.INITIATOR_ADDRESS_LENGTH: 0,
            self.ACCEPTOR_ADDRTYPE: 0,
            self.ACCEPTOR_ADDRESS_LENGTH: 0,
            self.APPLICATION_DATA_LENGTH: 0,
            self.INITIATOR_ADDRESS: b"",
            self.ACCEPTOR_ADDRESS: b"",
            self.APPLICATION_DATA: b""
        }

    def __setitem__(self, key, value):
        self.fields[key] = value

    def __getitem__(self, key):
        return self.fields[key]

    def get_data(self):
        # Set the lengths of each len field in case they have changed
        self[self.INITIATOR_ADDRESS_LENGTH] = len(self[self.INITIATOR_ADDRESS])
        self[self.ACCEPTOR_ADDRESS_LENGTH] = len(self[self.ACCEPTOR_ADDRESS])
        self[self.APPLICATION_DATA_LENGTH] = len(self[self.APPLICATION_DATA])

        # Add all the values together to create the gss_channel_bindings_struct
        data = struct.pack("<L", self[self.INITIATOR_ADDTYPE])
        data += struct.pack("<L", self[self.INITIATOR_ADDRESS_LENGTH])
        data += self[self.INITIATOR_ADDRESS]
        data += struct.pack("<L", self[self.ACCEPTOR_ADDRTYPE])
        data += struct.pack("<L", self[self.ACCEPTOR_ADDRESS_LENGTH])
        data += self[self.ACCEPTOR_ADDRESS]
        data += struct.pack("<L", self[self.APPLICATION_DATA_LENGTH])
        data += self[self.APPLICATION_DATA]

        return data
