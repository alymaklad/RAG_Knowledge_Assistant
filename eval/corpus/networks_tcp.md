# Computer Networks, Lecture 9: TCP

## What TCP provides

The Transmission Control Protocol (TCP) gives applications a reliable, in-order byte stream on top of IP, which only offers best-effort delivery of individual packets. IP packets can be lost, duplicated, reordered or corrupted; TCP hides all of this from the application.

TCP is connection-oriented and full-duplex: two endpoints set up a connection before exchanging data, and data flows in both directions at once. Every byte in the stream has a sequence number, and the receiver sends cumulative acknowledgements that name the next byte it expects.

TCP differs from UDP, which is connectionless and adds little beyond port numbers and a checksum to IP. UDP suits applications such as voice calls and DNS lookups, where low latency matters more than guaranteed delivery.

## The three-way handshake

A TCP connection is opened with a three-way handshake. The client sends a SYN segment carrying its initial sequence number. The server replies with a SYN-ACK segment that acknowledges the client's sequence number and carries the server's own initial sequence number. Finally the client sends an ACK that acknowledges the server's sequence number, and the connection is established.

Initial sequence numbers are chosen randomly rather than starting at zero. This prevents segments from an old connection between the same ports from being mistaken for part of a new one, and it makes it harder for an attacker to inject forged segments.

A SYN flood attack sends many SYN segments without completing the handshake, filling the server's table of half-open connections. SYN cookies defend against this by encoding the connection state in the server's initial sequence number, so the server stores nothing until the final ACK arrives.

---page---

## Reliability and retransmission

TCP detects loss in two ways. A retransmission timeout fires when an acknowledgement does not arrive in time; the timeout is computed from a smoothed estimate of the round-trip time plus four times its variation. Fast retransmit resends a segment as soon as the sender receives three duplicate acknowledgements for the data before it, without waiting for the timer.

## Flow control

Flow control stops a fast sender from overwhelming a slow receiver. The receiver advertises a receive window in every segment: the amount of free buffer space it has. The sender never has more unacknowledged data in flight than the advertised window.

If the receiver advertises a window of zero, the sender stops and periodically sends a small window probe so it learns when space opens up again.

## Congestion control

Congestion control protects the network rather than the receiver. The sender keeps a congestion window (cwnd), and the amount of data in flight is limited by the smaller of cwnd and the receive window.

Slow start begins with a small congestion window and doubles it every round-trip time, which is exponential growth. When cwnd reaches the slow-start threshold (ssthresh), TCP switches to congestion avoidance and grows the window by about one segment per round-trip time, which is linear growth.

This combination is called additive increase, multiplicative decrease (AIMD). On three duplicate acknowledgements, TCP Reno halves the congestion window and continues with fast recovery. On a timeout it treats the loss as severe: it sets ssthresh to half the window and restarts slow start from one segment.

---page---

## Closing a connection

Each direction of a TCP connection is closed separately. The side that finishes sending sends a FIN segment, and the other side acknowledges it. Closing both directions normally takes four segments: FIN, ACK, FIN, ACK.

The side that closes first enters the TIME_WAIT state after the exchange and waits for twice the maximum segment lifetime before releasing the connection. TIME_WAIT ensures that the final ACK can be retransmitted if it is lost and that delayed segments from the old connection die out before the same port pair is reused.

## Modern variants

TCP CUBIC, the default in Linux, replaces the linear growth of congestion avoidance with a cubic function of the time since the last loss, which uses high-bandwidth, long-delay links more efficiently. BBR, developed at Google, estimates the bottleneck bandwidth and round-trip time directly instead of treating packet loss as the signal of congestion.
