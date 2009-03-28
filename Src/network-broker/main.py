import socket, struct, syslog, time, thread
import SocketServer

FRODO_NETWORK_MAGIC = 0x1976

CONNECT_TO_BROKER  = 99 # Hello, broker
LIST_PEERS         = 98 # List of peers
CONNECT_TO_PEER    = 97 # A peer wants to connect
SELECT_PEER        = 93 # The client selects who to connect to
DISCONNECT         = 96 # Disconnect from a peer
PING               = 95 # Are you alive?
ACK                = 94 # Yep
STOP               = 55 # No more packets

def log(pri, msg, echo):
    syslog.syslog(pri, msg)
#    if echo:
    print msg

def log_error(msg, echo = False):
    log(syslog.LOG_ERR, msg, echo)

def log_warn(msg, echo = False):
    log(syslog.LOG_WARNING, msg, echo)

def log_info(msg, echo = False):
    log(syslog.LOG_INFO, msg, echo)

def cur_time():
    return time.mktime(time.localtime())

class Packet:
    def __init__(self):
        """Create a new packet"""
        self.magic = FRODO_NETWORK_MAGIC
        self.type = 0
        self.size = 8

    def demarshal_from_data(self, data):
        """Create a new packet from raw data. Data should always be in network
byte order"""
        self.magic = struct.unpack(">H", data[0:2])[0]
        self.type = struct.unpack(">H", data[2:4])[0]
        self.size = struct.unpack(">L", data[4:8])[0]

    def get_magic(self):
        return self.magic

    def get_type(self):
        return self.type

    def get_size(self):
        return self.size

    def marshal(self):
        return struct.pack(">HHL", self.magic, self.type, self.size)

class StopPacket(Packet):
    def __init__(self):
        Packet.__init__(self)
        self.type = STOP

    def marshal(self):
        return struct.pack(">HHL", self.magic, self.type, self.size)

class PingAckPacket(Packet):
    def __init__(self):
        Packet.__init__(self)
        self.type = PING
        self.seq = 0
        self.size = self.size + 4

    def set_seq(self, seq):
        self.seq = seq

    def demarshal_from_data(self, data):
        """Init a new packet from raw data."""
        Packet.demarshal_from_data(self, data)
        self.seq = struct.unpack(">L", data[8:12])[0]

    def marshal(self):
        """Create data representation of a packet"""
        return Packet.marshal(self) + struct.pack(">L", self.seq)


class SelectPeerPacket(Packet):
    def __init__(self):
        Packet.__init__(self)
        self.type = SELECT_PEER
        self.server_id = 0
        self.size = self.size + 4

    def demarshal_from_data(self, data):
        """Create a new packet from raw data."""
        Packet.demarshal_from_data(self, data)
        self.server_id = struct.unpack(">L", data[8:12])[0]

    def get_id(self):
        return self.server_id


class ConnectToBrokerPacket(Packet):

    def __init__(self):
        self.key = 0
        self._is_master = 0
        self.private_port = 0
        self.public_port = 0
        self.private_ip = ""
        self.public_ip = ""
        self.type = CONNECT_TO_BROKER
        self.name = ""
        self.server_id = 0

    def demarshal_from_data(self, data):
        Packet.demarshal_from_data(self, data)

        self.key = struct.unpack(">H", data[44:46])[0]
        self._is_master = struct.unpack(">H", data[46:48])[0]
        self.name = struct.unpack(">32s", data[48:48+32])[0]
        self.server_id = struct.unpack(">L", data[80:84])[0]

    def get_key(self):
        return self.key

    def get_name(self):
        return self.name

    def is_master(self):
        return self._is_master

class ListPeersPacket(Packet):
    def __init__(self):
        Packet.__init__(self)
        self.n_peers = 0
        self.peers = []
        self.type = LIST_PEERS
        self.size = self.size + 24

    def add_peer(self, peer):
        self.peers.append(peer)
        self.n_peers = self.n_peers + 1
        self.size = self.size + 76

    def marshal(self):
        out = struct.pack(">L16sHxx", self.n_peers, "", 0)

        for peer in self.peers:
            out = out + struct.pack(">HH16s16sHH32sL",
                                    0, peer.public_port, "",
                                    peer.public_ip, peer.key,
                                    peer.is_master, peer.name,
                                    peer.id)

        return Packet.marshal(self) + out



class Peer:
    def __init__(self, addr, srv, id):
        self.srv = srv

        self.addr = addr
        self.public_ip, self.public_port = self.addr_to_ip_and_port(addr)
        # These will be set by the CONNECT_TO_BROKER packet below
        self.key = 0
        self.name = ""
        self.is_master = 0
        self.id = id

        # Assume it's alive now
        self.last_ping = cur_time()

    def addr_to_ip_and_port(self, addr):
        ip = struct.unpack("@L", socket.inet_pton(socket.AF_INET, addr[0]))[0]
        port = addr[1]
        return "%08x" % (ip), port

    def handle_packet(self, pkt):
        if pkt.type == CONNECT_TO_BROKER:
            self.key = pkt.get_key()
            self.name = pkt.get_name()
            self.is_master = pkt.is_master()

            # Send list of peers if this is not a master
            if not self.is_master:
                lp = ListPeersPacket()

                # Remove inactive peers
                rp = []
                for peer in self.srv.peers.itervalues():
                    if peer != self and peer.seconds_since_last_ping() > 15:
                        rp.append(peer)
                for peer in rp:
                    log_info("Peer %s:%d has been inactive for %d seconds, removing" % (peer.addr[0],
                                                                                        peer.addr[1],
                                                                                        peer.seconds_since_last_ping()))
                    self.srv.remove_peer(peer)

                for peer in self.srv.peers.itervalues():
                    if peer != self and peer.is_master:
                        lp.add_peer(peer)
                # And send the packet to this peer
                log_info("Sending list of peers (%d) to %s:%d" % (lp.n_peers,
                                                                  self.addr[0], self.addr[1]) )
                self.send_packet(lp.marshal())

        if pkt.type == SELECT_PEER:
            peer = self.srv.get_peer_by_id( pkt.get_id() )

            # Tell the peer that we have connected
            lp = ListPeersPacket()
            lp.add_peer(self)
            log_info("Sending list of peers for peer selected to %s:%d" % (
                     self.addr[0], self.addr[1]))
            peer.send_packet( lp.marshal() )

            # These two are no longer needed
            self.srv.remove_peer(peer)
            self.srv.remove_peer(self)

        if pkt.type == ACK:
            self.last_ping = cur_time()

    def seconds_since_last_ping(self):
        now = cur_time()
        return now - self.last_ping

    def send_packet(self, data):
        self.srv.socket.sendto(data + StopPacket().marshal(),
                               0, self.addr)

    def __str__(self):
        return '%s:%d "%s" %d %d' % (self.public_ip, self.public_port,
                             self.name, self.key, self.is_master)

class BrokerPacketHandler(SocketServer.DatagramRequestHandler):
    def get_packet_from_data(self, data):
        magic = struct.unpack(">H", data[0:2])[0]
        type = struct.unpack(">H", data[2:4])[0]

        if magic != FRODO_NETWORK_MAGIC:
            raise Exception("Packet magic does not match: %4x vs %4x\n" % (magic,
                                                                           FRODO_NETWORK_MAGIC) )
        try:
            out = packet_class_by_type[type]()
            out.demarshal_from_data(data)
            return out
        except KeyError, e:
            raise Exception("Unknown packet type %d" % (type))

    def handle(self):
        srv = self.server
        data = self.rfile.read()

        try:
            pkt = self.get_packet_from_data(data)
        except Exception, e:
            log_error("Broken packet: %s" % e)
            return

        # Log received packets (except ping ACKs to avoid filling the server)
        if pkt.get_type() != ACK:
            log_info("Received packet %d from %s:%d" % (pkt.get_type(), self.client_address[0],
                                                        self.client_address[1]))

        peer = srv.get_peer(self.client_address)

        try:
            peer.handle_packet(pkt)
        except Exception, e:
            # Sends crap, let's remove it
            log_error("Handling packet failed, removing peer: %s" % e)
            srv.remove_peer(peer)

class Broker(SocketServer.UDPServer):

    def __init__(self, host, req_handler):
        SocketServer.UDPServer.__init__(self, host, req_handler)
        # Instead of setsockopt( ... REUSEADDR ... )
        self.allow_reuse_address = True
        self.peers = {}
        self.peers_by_id = {}
        self.id = 0
        self.ping_seq = 0

    def send_data(self, dst, data):
        self.socket.sendto(data, dst)

    def get_peer(self, key):
        "Return the peer for a certain key, or a new one if it doesn't exist"
        try:
            peer = self.peers[key]
        except KeyError, e:
            peer = Peer(key, self, self.id)
            self.peers[key] = peer
            self.peers_by_id[self.id] = peer
            self.id = self.id + 1
        return peer

    def get_peer_by_id(self, id):
        return self.peers_by_id[id]

    def get_peer_by_name_key(self, name, key):
        for k,v in self.peers.iteritems():
            if name == v.get_name() and key == v.get_key():
                return v
        return None

    def ping_all_peers(self):
        """Ping all peers (to see that they are alive)"""
        for k,v in self.peers.iteritems():
            p = PingAckPacket()
            p.set_seq(self.ping_seq)
            v.send_packet( p.marshal() )

        self.ping_seq = self.ping_seq + 1

    def remove_peer(self, peer):
        try:
            del self.peers[ peer.addr ]
            del self.peers_by_id[ peer.id ]
        except:
            log_error("Could not remove %s, something is wrong" % (str(peer.addr)))

def ping_thread_fn(broker, time_to_sleep):
    """Run as a separate thread to ping all peers"""

    while True:
        try:
            broker.ping_all_peers()
            time.sleep( time_to_sleep )
        except Exception, e:
            print e

# Some of the Frodo network packets. There are more packets, but these
# are not interesting to the broker (and shouldn't be sent there either!)
packet_class_by_type = {
    CONNECT_TO_BROKER : ConnectToBrokerPacket,
    SELECT_PEER : SelectPeerPacket,
    ACK : PingAckPacket,
}

if __name__ == "__main__":
    syslog.openlog("frodo")
    log_info("Starting Frodo network broker", True)
    broker = Broker( ("", 46214), BrokerPacketHandler)
    thread.start_new_thread(ping_thread_fn, (broker, 5))
    broker.serve_forever()
