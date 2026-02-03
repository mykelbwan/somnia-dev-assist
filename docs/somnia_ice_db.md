# Somnia's IceDB

Somnia also includes its own database called IceDB. It has three key properties:

1\. Deterministic performance&#x20;

2\. In-memory cache with read promotions&#x20;

3\. Built-in snapshotting&#x20;

## **Deterministic Performance**&#x20;

Most blockchains use an embedded database like [LevelsDB](https://github.com/google/leveldb) or [RocksDB](https://rocksdb.org/). These databases are often optimised for write throughput and eventually flush all written data to disk to maintain a steady RAM load.&#x20;

This means that reads from these databases can hit RAM or many different places on disk. Depending on where the value is stored, the latency difference is enormous, differing by up to 1000x.

So, how much gas should a user be charged for a read? Should we assume the worst-case scenario that every read hits disk multiple times? Or should we assume some amount will hit memory? The former drastically limits the speed of your blockchain, and the latter allows an attacker to critically slow down your chain.

Could we time the read on each node and charge the user based on how long the request took? Unfortunately not, as this would not be deterministic across nodes (LevelsDB, RocksDB, etc., make no attempt to store data in deterministic places). Therefore, we can not change the gas based on this information.

Somnia's IceDb has been built from the ground up to have fully deterministic performance. Every read and write to IceDb returns the result and a "performance report". This report details exactly how many cold cache lines were read from RAM, and exactly how many disk pages were read from the SSD.

Due to this information being deterministic, we can charge the user based on the actual load they put on the system. Reads that accessed frequent data (and therefore hit RAM) use less gas, and we can then fit more into the block.&#x20;

## **Improved read/write cache**

As mentioned above, databases that persist to the disk often have an in-memory cache which attempts to store frequently accessed data in RAM, to serve frequent data with a much lower latency.&#x20;

Most databases tend to optimise for either read or write. With Somnia, we have created a cache that can do both. This enables the average read/writes of IceDB to be between 15-100 nanoseconds.

## **Built-in Snapshotting**

Blockchains require all nodes to periodically agree on exactly which state is in the blockchain after a given block.

Most blockchains use a data structure such as a Merkle tree to retrieve a single-state hash that encapsulates all of the data in the blockchain. Merkle trees allow this hash to be updated with every write with reasonable performance while allowing proofs of a particular piece of state to be generated for parties without access to the database.

Most blockchains then store each node in this Merkle tree as standard keys into their database. This makes reads or writes from this tree very expensive, as every single node can result in massive latencies from these embedded databases.

The reality, however, is the data structure that these databases use under the hood (a log structured merge tree) already lends itself to a tree formation, with vast sections stored immutably on disk. IceDB utilises this underlying immutable structure to support first class state snapshots, without needing the user space execution engine to store a Merkle tree using the databases' key value abstraction.

This massively accelerates the performance of IceDB, and reduces the amount of overhead for each value.

<br>
