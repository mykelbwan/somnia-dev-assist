# What is Somnia Data Streams?

Somnia Data Streams is a structured data layer for EVM chains. Somnia Data streams enable developers to build applications that both emit EVM event logs and write data to the Somnia chain without Solidity. This means developers do not need to know Solidity to build applications using Somnia Data Streams.&#x20;

Somnia Data streams allow parsing schema data into contract storage, where developers define a schema (a typed, ordered layout of fields), then publish and subscribe to data that conforms to that schema.

Think of reading data from Streams as an emitted event, but with an SDK: publishers write strongly-typed records; subscribers read them by schema and publisher, and decode to rich objects.

***

## Why Streams?

Traditional approaches each have trade-offs:

* Contract events are great for signaling, but untyped at the app level (you still write your own ABI and decoders across projects). Events are also hard to stitch into reusable data models.<br>
* Custom contract storage is powerful but heavyweight, and you maintain the whole schema logic, CRUD, indexing patterns, and migrations.<br>
* Off-chain DB and proofs are flexible but brittle; either centralized or require extra machinery.<br>
* Oracles are useful for external data, but not a generic modeling layer for app-originated data.<br>

Streams solves this by standardizing:

1. Schemas (the “data ABI”)<br>
2. Publish/Subscribe primitives (SDK, not boilerplate contracts)<br>
3. Deterministic IDs (schemaId, dataId) and provenance (publisher address)<br>

This results in interoperable, verifiable, composable data with minimal app code.

***

## When to Use Streams

Use Streams when you need:

* Typed, shareable data across apps (chat messages, GPS, player stats, telemetry)
* Multiple publishers writing the same kind of record
* A standard decode flow with minimal custom indexing
* You need instant push to clients (Streams also works well with polling; you can add WS if desired)

Avoid Streams if:

* You need complex transactional logic/state machines tightly bound to contract invariants (build a contract)
* You must store large blobs (store off-chain, publish references/URIs in Streams)

***

## Definition of Terms

* **Schema**: a canonical string describing fields in order, e.g.\
  uint64 timestamp, bytes32 roomId, string content, string senderName, address sender\
  The exact string determines a schemaId (hash).<br>
* **Publisher**: The signer that writes data. EOA or Smart Contract that writes data under a schema. Readers trust provenance by address.<br>
* **Subscriber**: reader that fetches all records for a (schemaId, publisher) pair.<br>
* **Data ID (dataId)**: developer-chosen 32-byte key per record (helps with lookups, dedup, pagination). Pick dataIds with predictable structure to enable point lookups or pagination seeds. E.g:
  * Game: toHex('matchId-index', { size: 32 })
  * Chat: toHex('room-timestamp', { size: 32 })
  * GPS: toHex('device-epoch', { size: 32 })<br>
* **Encoder**: converts typed values ⇄ bytes according to the schema.<br>
* **schemaId**: computed from the schema string. Treat it like a contract address for data shape.

#### Data flow&#x20;

```markup
+-------------+        publishData(payload)         +--------------------+
|  Publisher  |  -------------------------------->  | Somnia Streams L1  |
|  (wallet)   |                                     |   (on-chain data)  |
+-------------+                                     +--------------------+
       ^                                                     |
       |                                     getAllPublisherDataForSchema
       |                                                     v
+-------------+                                        +-----------+
| Subscriber  |  <------------------------------------ |  Reader   |
| (frontend)  |                                        | (SDK)     |
+-------------+                                        +-----------+
```

You can have multiple publishers writing under the same schema; subscribers can aggregate them if desired.

***

## The Schema: Your “Data ABI”

A schema is a compact, ordered list of typed fields. The exact string determines the computed `schemaId` Even whitespace and order matter.

Design guidance

* Put stable fields first (e.g., timestamp, entityId, type).
* Prefer fixed-width ints (e.g., uint64 for timestamps).
* Use bytes32 for keys/IDs (room, device, etc.).
* Use string for human-readable info (names, messages), but keep it short for gas efficiency.<br>

***

### Data Writing Patterns

* Single Publisher\
  One server wallet publishes; User Interaces can read the schema using `getByKey` , `getAtIndex` , `getAllPublisherDataForSchema`.<br>
* Multi-Publisher \
  Many devices publish under a shared schema. Your API aggregates across a list of publisher addresses.<br>
* Derived Views\
  Build REST endpoints that query Streams and derive higher-level views (e.g., “latest per room”).

***

## Quickstart in 5 Minutes

You’ll register a schema, publish one message, and read it back — just to feel the flow.

### Install

```bash
npm i @somnia-chain/streams viem
```

### Set up Env

```markup
RPC_URL=https://dream-rpc.somnia.network
PRIVATE_KEY=0xYOUR_FUNDED_PRIVATE_KEY
```

### Define Chain

```typescript
// lib/chain.ts
import { defineChain } from 'viem'
export const somniaTestnet = defineChain({
  id: 50312, name: 'Somnia Testnet', network: 'somnia-testnet',
  nativeCurrency: { name: 'STT', symbol: 'STT', decimals: 18 },
  rpcUrls: { default: { http: ['https://dream-rpc.somnia.network'] }, public: { http: ['https://dream-rpc.somnia.network'] } },
} as const)
```

### Define Client

```typescript
// lib/clients.ts
import { createPublicClient, createWalletClient, http } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { somniaTestnet } from './chain'

const RPC = process.env.RPC_URL as string
const PK  = process.env.PRIVATE_KEY as `0x${string}`

export const publicClient = createPublicClient({ chain: somniaTestnet, transport: http(RPC) })
export const walletClient = createWalletClient({ account: privateKeyToAccount(PK), chain: somniaTestnet, transport: http(RPC) })
```

### Schema

```typescript
// lib/schema.ts
export const chatSchema =
  'uint64 timestamp, bytes32 roomId, string content, string senderName, address sender'
```

#### Register Schema (optional but recommended)

<details>

<summary>scripts/register.ts</summary>

```typescript
import 'dotenv/config'
import { SDK, zeroBytes32 } from '@somnia-chain/streams'
import { publicClient, walletClient } from '../lib/clients'
import { chatSchema } from '../lib/schema'
import { waitForTransactionReceipt } from 'viem/actions'


async function main() {
  const sdk = new SDK({ public: publicClient, wallet: walletClient })
  const id = await sdk.streams.computeSchemaId(chatSchema)
  const exists = await sdk.streams.isSchemaRegistered(id)
  if (!exists) {
    const tx = await sdk.streams.registerSchema(chatSchema, zeroBytes32)
    await waitForTransactionReceipt(publicClient, { hash: tx })
  }
  console.log('schemaId:', id)
}
main()
```

</details>

### Publish (Write)

```typescript
// scripts/publish-one.ts
import 'dotenv/config'
import { SDK, SchemaEncoder } from '@somnia-chain/streams'
import { publicClient, walletClient } from '../lib/clients'
import { chatSchema } from '../lib/schema'
import { toHex, type Hex } from 'viem'
import { waitForTransactionReceipt } from 'viem/actions'

async function main() {
  const sdk = new SDK({ public: publicClient, wallet: walletClient })
  const schemaId = await sdk.streams.computeSchemaId(chatSchema)
  const enc = new SchemaEncoder(chatSchema)

  const payload: Hex = enc.encodeData([
    { name: 'timestamp',  value: Date.now().toString(),    type: 'uint64' },
    { name: 'roomId',     value: toHex('general', { size: 32 }), type: 'bytes32' },
    { name: 'content',    value: 'Hello Somnia!',          type: 'string' },
    { name: 'senderName', value: 'Alice',                  type: 'string' },
    { name: 'sender',     value: walletClient.account!.address, type: 'address' },
  ])

  const dataId = toHex(`general-${Date.now()}`, { size: 32 })
  const tx = await sdk.streams.setAndEmitEvents(
    [{ id: dataId, schemaId, data }],
    [{ id: CHAT_EVENT_ID, argumentTopics: topics.slice(1), data: eventData }]
  )

  if (!tx) throw new Error('Failed to setAndEmitEvents')
  await waitForTransactionReceipt(getPublicHttpClient(), { hash: tx })
  return { txHash: tx }
}
main()
```

### &#x20;Read Data

```typescript
// scripts/read-all.ts
import 'dotenv/config'
import { SDK } from '@somnia-chain/streams'
import { publicClient } from '../lib/clients'
import { chatSchema } from '../lib/schema'
import { toHex } from 'viem'

type Field = { name: string; type: string; value: any }
const val = (f: Field) => f?.value?.value ?? f?.value

async function main() {
  const sdk = new SDK({ public: publicClient })
  const schemaId = await sdk.streams.computeSchemaId(chatSchema)
  const publisher = process.env.PUBLISHER as `0x${string}` || '0xYOUR_PUBLISHER_ADDR'

  const rows = (await sdk.streams.getAllPublisherDataForSchema(schemaId, publisher)) as Field[][]
  const want = toHex('general', { size: 32 }).toLowerCase()

  for (const r of rows || []) {
    const ts = Number(val(r[0]))
    const ms = String(ts).length <= 10 ? ts * 1000 : ts
    if (String(val(r[1])).toLowerCase() !== want) continue
    console.log({
      time: new Date(ms).toLocaleString(),
      content: String(val(r[2])),
      senderName: String(val(r[3])),
      sender: String(val(r[4])),
    })
  }
}
main()

```

That’s your first end-to-end loop.

***

## FAQs

Q: Do I need to register a schema?\
A: Registration is optional but recommended. You can publish to an unregistered schema (readers just need the exact string to decode). Registration helps discoverability and tooling.

Q: Can I change a schema later?\
A: Changing order or types yields a new schemaId. Plan for versioning (run v1 + v2 together).

Q: How do I page data?\
A: Use structured dataIds, or build a thin index off-chain that records block numbers / tx hashes per record.

Q: How does Streams differ from subgraphs?\
A: Streams defines how you write/read structured records with an SDK. Subgraphs (or other indexers) sit on top to query across many publishers, paginate, and filter efficiently.

Q: How do I handle large payloads?\
A: Store the payload elsewhere (IPFS, Arweave, S3) and put the URI + hash in Streams. Optionally encrypt off-chain.

# Quickstart

## Pre-requisites

A typescript environment with [`viem`](https://viem.sh/) and [`@somnia-chain/streams`](https://www.npmjs.com/package/@somnia-chain/streams) installed

## Steps

### 1. Define your schema as a string and plug it into the schema encoder

```typescript
import { SDK, zeroBytes32, SchemaEncoder } from "@somnia-chain/streams"

const gpsSchema = `uint64 timestamp, int32 latitude, int32 longitude, int32 altitude, uint32 accuracy, bytes32 entityId, uint256 nonce`
const schemaEncoder = new SchemaEncoder(gpsSchema)
```

`schemaEncoder` can now be used to encode data for broadcast and also decode data when reading it from Somnia Data Stream SDK.

### 2. Compute your unique schema identifier from the schema

<pre class="language-typescript"><code class="lang-typescript"><strong>const sdk = new SDK({
</strong>    public: getPublicClient(),
    wallet: getWalletClient(),
})
const schemaId = await sdk.streams.computeSchemaId(gpsSchema)
console.log(`Schema ID ${schemaId}`)
</code></pre>

All data broadcast with the Somnia Data Stream SDK write mechanism must be linked to a schema ID so that we know how to decode the data on read.

### 3. Encode the data you want to store that is compatible with the schema

```typescript
const encodedData: Hex = schemaEncoder.encodeData([
    { name: "timestamp", value: Date.now().toString(), type: "uint64" },
    { name: "latitude", value: "51509865", type: "int32" },
    { name: "longitude", value: "-0118092", type: "int32" },
    { name: "altitude", value: "0", type: "int32" },
    { name: "accuracy", value: "0", type: "uint32" },
    { name: "entityId", value: zeroBytes32, type: "bytes32" }, // object providing GPS data
    { name: "nonce", value: "0", type: "uint256" },
])
```

The value returned is a raw hex encoded bytes value that can be broadcast on-chain via the Somnia Data Stream SDK.&#x20;

### 4. Publish data (with our without a public schema)

```typescript
const publishTxHash = await sdk.streams.set([{
    id: toHex("london", { size: 32 }),
    schemaId: computedGpsSchemaId,
    data: encodedData,
}])
```

`set` has the following parameter `dataStreams` which is a list of data points being written to chain\
\
`dataStreams` has the `DataStream[]` type:

```typescript
type Hex = `0x{string}`
type DataStream = {
    id: Hex // Unique data key for the publisher
    schemaId: Hex // Computed from the raw schema string
    data: Hex // From step 3, raw bytes data formated as a hex string
}
```

### 5. Direct data read without reactivity

```typescript
const data = await sdk.streams.getByKey(
  computedGpsSchemaId,
  publisherWalletAddress,
  dataKey
)
```

This last step shows how you request data from Somnia data streams filtering on:

1. Schema ID
2. Address of the account that wrote the data to chain
   1. This could be an EOA or another smart contract

The response from `getByKey` will be the data published but decoded for the specified schema.&#x20;

Note: where the schema ID is associated with a public data schema that has been registered on-chain, the SDK will automatically decode the raw data published on-chain and return that decoded data removing the need for the decoder. If the schema is not public, the schema decoder will be required outside of the SDK and you will instead get raw bytes from the chain. Example:

```typescript
if (data) {
  schemaEncoder.decode(data)
}
```

Further filters can be applied client side to the data in order to filter for specifics within the data. GitBook also allows you to set up a bi-directional sync with an existing repository on GitHub or GitLab. Setting up Git Sync allows you and your team to write content in GitBook or in code, and never have to worry about your content becoming out of sync.


# Understanding Schemas, Schema IDs, Data IDs, and Publisher

Somnia Data Streams uses a schema-driven architecture to store and manage blockchain data. Every piece of information stored on the network, whether it’s a chat message, leaderboard score, or todo item, follows a structured schema, is identified by a Schema ID, written with a Data ID, and associated with a Publisher.

In this guide, you’ll learn the difference between Schemas and Schema IDs, how Data IDs uniquely identify records, and how Publishers own and manage their data streams.

* Schemas define the structure of your data.
* Data IDs uniquely identify individual records.
* Publisher determines who owns or controls the data stream.

By the end, you’ll understand how to organize, reference, and manage your application’s data on Somnia.

## What Are Schemas?

A Schema defines the structure and types of the data you want to store onchain. It’s like a blueprint for how your application’s data is encoded, stored, and decoded. A Schema ID, on the other hand, is a unique deterministic hash computed from that schema definition.

When you register or compute a schema, the SDK automatically generates a unique hash (Schema ID) that permanently represents that schema definition.

A schema describes the structure of your data, much like a table in a relational database defines its columns.

#### Example: Defining a Schema

```typescript
const userSchema = `
  uint64 timestamp,
  string username,
  string bio,
  address owner
`
```

This schema tells the Somnia Data Streams system how your data is structured and typed.&#x20;

## Schema ID: The Unique Identifier

A Schema ID is derived from your schema using a hashing algorithm. It uniquely represents this structure onchain, ensuring consistency and integrity. You can compute its Schema ID before even deploying it onchain.

```typescript
import { SDK } from '@somnia-chain/streams'
import { getSdk } from './clients'

const sdk = getSdk()
const schemaId = await sdk.streams.computeSchemaId(userSchema)

console.log("Computed Schema ID:", schemaId)
```

Example Output:

```bash
Computed Schema ID: 0x5e4bce54a39b42b5b8a235b5d9e27e7031e39b65d7a42a6e0ac5e8b2c79e17b0

```

This hash (schemaId) uniquely identifies the schema onchain. If you change even one character in the schema definition, the Schema ID will change.

The Schema ID is the hash that ensures the same structure is used everywhere, preventing mismatched or corrupted data.

## Registering a Schema

To make the schema usable onchain, it has to be registered by calling the `registerDataSchemas()` method. This ensures other nodes and apps can decode your data correctly:

```typescript
import { zeroBytes32 } from '@somnia-chain/streams'

const ignoreExistingSchemas = true
await sdk.streams.registerDataSchemas([
  { schemaName: "MySchema", schema: userSchema, parentSchemaId: zeroBytes32 }
], ignoreExistingSchemas)
```

`id` is a string. human human-readable identifier`ignoreExistingSchemas` is for telling the SDK not to worry about already registered schemas.\
Once registered, any publisher can use this Schema ID to store or retrieve data encoded according to this structure. The schema defines structure. The Schema ID becomes its permanent onchain reference.

| Concept   | Database Equivalent | Description                                |
| --------- | ------------------- | ------------------------------------------ |
| Schema    | Table Definition    | Defines data fields and types              |
| Schema ID | Table Hash          | Uniquely identifies that schema definition |

For instance:

`Schema  → CREATE TABLE Users (id INT, name TEXT)`

`Schema ID → 0x9f3a...a7c (hash of the above definition)`

## What Are Data IDs?

Every record written to Somnia (e.g., a single message, transaction, or post) must have a Data ID, a unique key representing that entry. It uniquely identifies a specific record (or row). The Data ID ensures that:

* Each entry can be updated or replaced deterministically.
* Developers can reference or fetch a specific record by key.
* Duplicate writes can be prevented.

#### Example: Creating a Data ID

A Data ID can be created by hashing a string, typically by combining context and timestamp.

```typescript
import { toHex } from 'viem'

const dataId = toHex(`username-${Date.now()}`, { size: 32 })
console.log("Data ID:", dataId)
```

Example Output:

```bash
Data ID: 0x757365726e616d652d31373239303239323435
```

You can now use this ID to publish structured data to the blockchain. A Data ID ensures every record written is unique and can be referenced or updated deterministically.

#### Example: Writing Data with a Schema and Data ID

```typescript
import { SchemaEncoder } from '@somnia-chain/streams'

const encoder = new SchemaEncoder(userSchema)
const encodedData = encoder.encodeData([
  { name: 'timestamp', value: Date.now().toString(), type: 'uint64' },
  { name: 'username', value: 'Victory', type: 'string' },
  { name: 'bio', value: 'Blockchain Developer', type: 'string' },
  { name: 'owner', value: '0xYourWalletAddress', type: 'address' },
])

await sdk.streams.set([
  { id: dataId, schemaId, data: encodedData }
])
```

Think of a Data ID like a primary key in a SQL table.

| Data ID (Primary Key) | username | bio                  |
| --------------------- | -------- | -------------------- |
| 0x1234abcd...         | Emmanuel | Blockchain Developer |

If you write another record with the same Data ID, it updates the existing entry rather than duplicating it, thereby maintaining data integrity. `schemaId` defines how to encode/decode the data, and `dataId` identifies which record this is. The data itself is encoded and written to the blockchain

## What Are Publishers?

A Publisher is any wallet address that sends data to Somnia Streams. Each publisher maintains its own isolated namespace for all schema-based data it writes. This means:

* Data from two different publishers never conflict.
* Apps can filter or query data from a specific publisher.
* Publishers serve as the data owners for all records they create.

#### Example: Getting a Publisher Address

If you’re using a connected wallet, your publisher is automatically derived using the `createWalletClient` from viem:

```typescript
const {
    ...
    createWalletClient,
} = require("viem");

const { privateKeyToAccount } = require("viem/accounts");

// Create wallet client
const walletClient = createWalletClient({
    account: privateKeyToAccount(process.env.PRIVATE_KEY),
    chain: dreamChain,
    transport: http(dreamChain.rpcUrls.default.http[0]),
});

// Initialize SDK
const sdk = new SDK({
    ...
    wallet: walletClient,
});

const encodedData = schemaEncoder.encodeData([
       ...
    { name: "sender", value: wallet.account.address, type: "address" },
]);
```

Where `publisher = wallet.account.address`&#x20;

When reading data, you can specify which publisher’s records to fetch:

```typescript
const messages = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisherAddress)
```

Example Output:

```bash
[
  { timestamp: 1729302920, username: "Victory", bio: "Blockchain Developer" }
]
```

This retrieves all data published under that schema by that particular address.

Think of Publishers like individual database owners. Each one maintains their own “tables” (schemas) and “records” (data entries) under their unique namespace.

| Publisher (Wallet) | Schema ID | Data ID | Description      |
| ------------------ | --------- | ------- | ---------------- |
| 0x123...abc        | Schema A  | Data 1  | Paul’s todos     |
| 0x789...def        | Schema A  | Data 2  | Emmanuel’s todos |

## Putting It All Together

When you publish data on Somnia, three identifiers always work together:

| Concept   | Role                   | Example         |
| --------- | ---------------------- | --------------- |
| Schema ID | Identifies schema hash | 0x5e4bce54...   |
| Data ID   | Identifies record      | 0x75736572...   |
| Publisher | Identifies sender      | 0x3dC360e038... |

These three make your data verifiable, queryable, and uniquely name-spaced across the blockchain. These form the foundation of the Somnia Data Streams architecture:

* The Schema tells the system what kind of data this is.
* The Schema ID ensures it’s stored consistently across the network.
* The Data ID identifies which record this is.
* The Publisher records who wrote it.

## Example Use Case: Chat Messages

Here’s how they interact in a real-world scenario,  a decentralized chat room.

### Step 1: Define Schema

```typescript
const chatSchema = `
  uint64 timestamp,
  bytes32 roomId,
  string content,
  string senderName,
  address sender
`
```

### Step 2: Compute Schema ID

```typescript
const schemaId = await sdk.streams.computeSchemaId(chatSchema)
```

### Step 3: Generate Data ID for each message

```typescript
const dataId = toHex(`${roomName}-${Date.now()}`, { size: 32 })
```

### Step 4: Publish Message

```typescript
const encoded = encoder.encodeData([
  { name: 'timestamp', value: Date.now().toString(), type: 'uint64' },
  { name: 'roomId', value: toHex(roomName, { size: 32 }), type: 'bytes32' },
  { name: 'content', value: 'Hello world!', type: 'string' },
  { name: 'senderName', value: 'Victory', type: 'string' },
  { name: 'sender', value: publisherAddress, type: 'address' }
])

await sdk.streams.set([{ id: dataId, schemaId, data: encoded }])
```

Now each message:

* Conforms to a schema
* Is identified by a Schema ID
* Is stored under a unique Data ID
* Is published by a specific Publisher

### Common Pitfalls

| Mistake                       | Description                        | Fix                                                                                                             |
| ----------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Reusing Data IDs incorrectly  | Causes overwrites of older records | Use unique IDs like title-timestamp                                                                             |
| Forgetting to register schema | Data won’t decode properly         | Always call registerDataSchemas() once                                                                          |
| Mixing publisher data         | Leads to incomplete reads          | Query by the correct publisher address and consider aggregating many publishers under a single contract address |

### Conclusion

Now that you understand Schemas, Data IDs, and Publishers, you’re ready to build your own data model for decentralized apps and query live data across multiple publishers


# Extending and composing data schemas

New schemas can extend other schemas by setting a parent schema ID. Remember, you can take any raw schema string and compute a schema ID from it. When registering a new schema that builds upon and extends another, you would specify the raw schema string for the new schema as well as specifying the optional parent schema ID. The parent schema ID will be critical later for deserialising data written to chain. \
\
For schemas that do not extend other schemas (when nothing is available), then one does not need to specify a parent schema ID or can optionally specify the zero value for the bytes32 solidity type.\
\
For maximum composability, all schemas should be public.

### Extension in practice (Example 1)

<pre class="language-typescript"><code class="lang-typescript"><strong>import { SDK } from "@somnia-chain/streams"
</strong><strong>const sdk = new SDK({
</strong>    public: getPublicClient(),
    wallet: getWalletClient(),
})

// The parent schema here will be the GPS schema from the quick start guide
const gpsSchema = `uint64 timestamp, int32 latitude, int32 longitude, int32 altitude, uint32 accuracy, bytes32 entityId, uint256 nonce`
const parentSchemaId = await sdk.streams.computeSchemaId(gpsSchema)

// Lets extend the gps schema and add F1 data since every car will have a gps position
const formulaOneSchema = `uint256 driverNumber`

// We can also extend the gps schema for FR data i.e. aircraft identifier
const flightRadarSchema = `bytes32 ICAO24`

await sdk.streams.registerDataSchemas([
    { schemaName: "gps", schema: gpsSchema },
    { schemaName: "f1", schema: formulaOneSchema, parentSchemaId }, // F1 extends GPS
    { schemaName: "FR", schema: flightRadarSchema, parentSchemaId },// FR extends GPS
])
</code></pre>

The typescript code shows how two new schemas re-use the GPS schema in order to append an additional field&#x20;

### Extension in practice (Example 2)

Versioned schemas

```typescript
import { SDK } from "@somnia-chain/streams"
const sdk = new SDK({
    public: getPublicClient(),
    wallet: getWalletClient(),
})

const versionSchema = `uint16 version`
const parentSchemaId = await sdk.streams.computeSchemaId(versionSchema)

// Now lets register a person schema with expectation there will be many versions of the person schema
const personSchema = `uint8 age` 
await sdk.streams.registerDataSchemas([
    { schemaName: "version", schema: versionSchema },
    { schemaName: "person", schema: personSchema, parentSchemaId }
])
```

Client's that are reading data associated with the derived schemas, use the SDK to get the fully decoded data since data is retrieved by schema ID (See `getByKey` from the quick start guide). Essentially the SDK does a number of the following pseudo steps:

1. Fetch schema and recursively fetch parent schema until the end of the chain is reached
2. Join all schemas together seperated by comma
3. Spin up the decoder and pass through the raw data stored on-chain
4. Return the decoded data to the caller


# Somnia Data vs Event Streams

### tl;dr

* Data Streams: Raw bytes calldata written to chain with contextual information on how to parse the data using a public or private `data schema`
* Event Streams: [EVM logs](https://docs.chainstack.com/docs/ethereum-logs-tutorial-series-logs-and-filters) emitted by the Somnia Streams protocol. Protocol users register and `event schema` that can be referenced they want to emit an event that others can `subscribe` to with Somnia streams reactivity

Both data and event streams can be done without knowing Solidity and without deploying any smart contracts

### TypeScript SDK interface

```typescript
/**
 * @param somniaStreamsEventId The identifier of a registered event schema within Somnia streams protocol or null if using a custom event source
 * @param ethCalls Fixed set of ETH calls that must be executed before onData callback is triggered. Multicall3 is recommended. Can be an empty array
 * @param context Event sourced selectors to be added to the data field of ETH calls, possible values: topic0, topic1, topic2, topic3, topic4, data and address
 * @param onData Callback for a successful reactivity notification
 * @param onError Callback for a failed attempt 
 * @param eventContractSource Alternative contract event source (any on somnia) that will be emitting the logs specified by topicOverrides
 * @param topicOverrides Optional when using Somnia streams as an event source but mandatory when using a different event source
 * @param onlyPushChanges Whether the data should be pushed to the subscriber only if eth_call results are different from the previous
 */
export type SubscriptionInitParams = {
    somniaStreamsEventId?: string
    ethCalls: EthCall[]
    context?: string
    onData: (data: any) => void
    onError?: (error: Error) => void
    eventContractSource?: Address
    topicOverrides?: Hex[]
    onlyPushChanges: boolean
}

export interface StreamsInterface {
    // Write
    set(d: DataStream[]): Promise<Hex | null>;
    emitEvents(e: EventStream[]): Promise<Hex | Error | null>;
    setAndEmitEvents(d: DataStream[], e: EventStream[]): Promise<Hex | Error | null>;

    // Manage
    registerDataSchemas(registrations: DataSchemaRegistration[]): Promise<Hex | Error | null>;
    registerEventSchemas(ids: string[], schemas: EventSchema[]): Promise<Hex | Error | null>;
    manageEventEmittersForRegisteredStreamsEvent(
        streamsEventId: string,
        emitter: Address,
        isEmitter: boolean
    ): Promise<Hex | Error | null>;

    // Read
    getByKey(schemaId: SchemaID, publisher: Address, key: Hex): Promise<Hex[] | SchemaDecodedItem[][] | null>;
    getAtIndex(schemaId: SchemaID, publisher: Address, idx: bigint): Promise<Hex[] | SchemaDecodedItem[][] | null>;
    getBetweenRange(
        schemaId: SchemaID,
        publisher: Address,
        startIndex: bigint,
        endIndex: bigint
    ): Promise<Hex[] | SchemaDecodedItem[][] | Error | null>;
    getAllPublisherDataForSchema(
        schemaReference: SchemaReference,
        publisher: Address
    ): Promise<Hex[] | SchemaDecodedItem[][] | null>;
    getLastPublishedDataForSchema(
        schemaId: SchemaID,
        publisher: Address
    ): Promise<Hex[] | SchemaDecodedItem[][] | null>;
    totalPublisherDataForSchema(schemaId: SchemaID, publisher: Address): Promise<bigint | null>;
    isDataSchemaRegistered(schemaId: SchemaID): Promise<boolean | null>;
    computeSchemaId(schema: string): Promise<Hex | null>;
    parentSchemaId(schemaId: SchemaID): Promise<Hex | null>;
    schemaIdToId(schemaId: SchemaID): Promise<string | null>;
    idToSchemaId(id: string): Promise<Hex | null>;
    getAllSchemas(): Promise<string[] | null>;
    getEventSchemasById(ids: string[]): Promise<EventSchema[] | null>;

    // Helper
    deserialiseRawData(
        rawData: Hex[],
        parentSchemaId: Hex,
        schemaLookup: {
            schema: string;
            schemaId: Hex;
        } | null
    ): Promise<Hex[] | SchemaDecodedItem[][] | null>;

    // Subscribe
    subscribe(initParams: SubscriptionInitParams): Promise<{ subscriptionId: string, unsubscribe: () => void } | undefined>;

    // Protocol
    getSomniaDataStreamsProtocolInfo(): Promise<GetSomniaDataStreamsProtocolInfoResponse | Error | null>;
}
```


# Intersection with Somnia Reactivity

## Reactivity background

For detailed information about reactivity please visit the Reactivity docs:

<table data-view="cards"><thead><tr><th></th><th data-hidden data-card-target data-type="content-ref"></th></tr></thead><tbody><tr><td>Reactivity</td><td><a href="../../../reactivity#welcome-to-the-somnia-reactivity-docs">#welcome-to-the-somnia-reactivity-docs</a></td></tr></tbody></table>

## Writing data, events and reacting

When an ERC20 transfer takes place, balance state is updated and an event is emitted. The ERC20 transfer scenario is very common in smart contracts i.e. publishing state and emitting an event (also known as a log). Somnia Data Streams offers you the tooling to do this without the requirements of having to write your own custom Solidity contract. It also allows you to take advantage of existing schemas for publishing data yielding composibility benefits for applications.\
\
Example:

```typescript
import { SDK } from "@somnia-chain/streams"
import { zeroAddress, erc721Abi } from "viem"

// Use WebSocket transport in the public client for subscription tasks
// For the SDK instance that executes transactions, stick with htttp
const sdk = new SDK({
    public: getPublicClient(),
    wallet: getWalletClient(),
})

// Encode view function calls to be executed when an event takes place
const ethCalls = [{
    to: "0x23B66B772AE29708a884cca2f9dec0e0c278bA2c",
    data: encodeFunctionData({
        abi: erc721Abi,
        functionName: "balanceOf",
        args: ["0x3dC360e0389683cA0341a11Fc3bC26252b5AF9bA"]
    })
}]

// Start a subsciption
const subscription = await sdk.streams.subscribe({

    ethCalls,
    onData: (data) => {
        const decodedLog = decodeEventLog({
            abi: fireworkABI,
            topics: data.result.topics,
            data: data.result.data,
        });

        const decodedFunctionResult = decodeFunctionResult({
            abi: erc721Abi,
            functionName: 'balanceOf',
            data: data.result.simulationResults[0],
        });

        console.log("Decoded event", decodedLog);
        console.log("Decoded function call result", decodedFunctionResult);
    }
})

// Write data and emit events that will trigger the above callback!
const dataStreams = [{
    id,
    schemaId: driverSchemaId,
    data: encodedData
}]

const eventStreams = [{
    id: somniaStreamsEventId,
    argumentTopics,
    data
}]

const setAndEmitEventsTxHash = await sdk.streams.setAndEmitEvents(
    dataStreams,
    eventStreams
)
```

Writing data and emitting events will trigger a call back to subscribers that care about a specified event emitted from the Somnia Data Streams protocol (or any contract for that matter) without having the need to poll the chain. It follows the observer pattern meaning push rather than pull which is always a more efficient paradigm.


# Data Provenance and Verification in Streams

When consuming data from any source, especially in a decentralized environment, the most critical question is: **"Can I trust this data?"**

This question is not just about the data's content, but its *origin*. How do you know that data claiming to be from a trusted oracle, a specific device, or another user *actually* came from them and not from an imposter?

This is the challenge of **Data Provenance**.

In Somnia Data Streams, provenance is not an optional feature or a "best practice". It is a fundamental, cryptographic guarantee built into the core smart contract. This article explains how Streams ensures authenticity via publisher signatures and how you can verify data origin.

## The Cryptographic Guarantee: `msg.sender` as Provenance

The trust layer of Somnia Streams is elegantly simple. It does not rely on complex off-chain signature checking or data fields like `senderName`. Instead, it leverages the most basic and secure primitive of the EVM: `msg.sender`.

All data published to Streams is stored in the core `Streams` smart contract. The data storage mapping has a specific structure:

#### **Conceptual Contract Storage**

```solidity
// mapping: schemaId => publisherAddress => dataId => data
mapping(bytes32 => mapping(address => mapping(bytes32 => bytes))) public dsstore;
```

When a publisher calls `sdk.streams.set(...)` or `sdk.streams.setAndEmitEvents(...)`, their wallet signs a transaction. The `Streams` smart contract receives this transaction and identifies the signer's address via the `msg.sender` variable.

The contract then stores the data *at the `msg.sender`'s address* within the schema's mapping.

**This is the cryptographic guarantee.**

It is **impossible** for `0xPublisher_A` to send a transaction that writes data into the slot for `0xPublisher_B`. They cannot fake their `msg.sender`. The data is automatically and immutably tied to the address of the account that paid the gas to publish it.

* An attacker **cannot** write data as if it came from a trusted oracle.
* A user **cannot** send a chat message pretending to be another user.
* Data integrity is linked directly to wallet security.

## Verification Is Implicit in the Read Operation

Because the `publisher` address is a fundamental key in the storage mapping, you don't need to perform complex "verification" steps. **Verification is implicit in the read operation.**

When you use the SDK to read data, you must specify which publisher you are interested in:

* `sdk.streams.getByKey(schemaId, publisher, key)`
* `sdk.streams.getAllPublisherDataForSchema(schemaId, publisher)`

When you call `getAllPublisherDataForSchema(schemaId, '0xTRUSTED_ORACLE_ADDRESS')`, you are not *filtering* data. You are asking the smart contract to retrieve data from the specific storage slot that *only* `0xTRUSTED_ORACLE_ADDRESS` could have written to.

If an imposter (`0xIMPOSTER_ADDRESS`) publishes data using the same `schemaId`, their data is stored in a completely different location (`dsstore[schemaId]['0xIMPOSTER_ADDRESS']`). It will never be returned when you query for the trusted address.

## Deliverable: Building a Verification Script

Let's build a utility to prove this concept.

**Scenario:** We have a shared `oraclePrice` schema. Two different, trusted oracles (`0xOracle_A` and `0xOracle_B`) publish prices to it. We will build a script that verifies the origin of data and proves that an `imposter` cannot pollute their feeds.

### **Project Setup**

We will use the same project setup as the "[Multi-Publisher Aggregator](https://emre-gitbook.gitbook.io/emre-gitbook-docs/data-streams/working-with-multiple-publishers-in-a-shared-stream#tutorial-building-a-multi-publisher-aggregator-app)" tutorial. You will need a `.env` file with at least one private key to act as a publisher, and we will simulate the other addresses.

[**`src/lib/clients.ts`**](https://emre-gitbook.gitbook.io/emre-gitbook-docs/data-streams/working-with-multiple-publishers-in-a-shared-stream#chain-and-client-configuration) (No changes needed from the previous tutorial. We just need `publicClient`.)

**`src/lib/schema.ts`**

```typescript
export const oraclePriceSchema = 'uint256 price, uint64 timestamp'
```

### **The Verification Script**

This script will not publish data. We will assume our two trusted oracles (`PUBLISHER_1_PK` and `PUBLISHER_2_PK` from the previous tutorial) have already published data using the `oraclePriceSchema`.

Our script will:

1. Define a list of `TRUSTED_ORACLES`.
2. Define an `IMPOSTER_ORACLE` (a random address that has *not* published).
3. Create a `verifyPublisher` function that fetches data *only* for a specific publisher address.
4. Run verification for all addresses and show that data is only returned for the correct publishers.

**`src/scripts/verifyOrigin.ts`**

```typescript
import 'dotenv/config'
import { SDK, SchemaDecodedItem } from '@somnia-chain/streams'
import { publicClient } from '../lib/clients' // Assuming you have clients.ts from previous tutorial
import { oraclePriceSchema } from '../lib/schema'
import { Address, createWalletClient, http } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'

// --- Setup: Define our trusted and untrusted addresses ---

function getEnv(key: string): string {
  const value = process.env[key]
  if (!value) throw new Error(`Missing environment variable: ${key}`)
  return value
}

// These are the addresses we trust for this schema.
// We get them from our .env file for this example.
const TRUSTED_ORACLES: Address[] = [
  privateKeyToAccount(getEnv('PUBLISHER_1_PK') as `0x${string}`).address,
  privateKeyToAccount(getEnv('PUBLISHER_2_PK') as `0x${string}`).address,
]

// This is a random, untrusted address.
const IMPOSTER_ORACLE: Address = '0x1234567890123456789012345678901234567890'

// --- Helper Functions ---

// Helper to decode the oracle data
function decodePriceRecord(row: SchemaDecodedItem[]): { price: bigint, timestamp: number } {
  const val = (field: any) => field?.value?.value ?? field?.value ?? ''
  return {
    price: BigInt(val(row[0])),
    timestamp: Number(val(r[1])),
  }
}

/**
 * Verification Utility
 * Fetches data for a *single* publisher to verify its origin.
 */
async function verifyPublisher(sdk: SDK, schemaId: `0x${string}`, publisherAddress: Address) {
  console.log(`\n--- Verifying Publisher: ${publisherAddress} ---`)
  
  try {
    const data = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisherAddress)
    
    if (!data || data.length === 0) {
      console.log('[VERIFIED] No data found for this publisher.')
      return
    }

    const records = (data as SchemaDecodedItem[][]).map(decodePriceRecord)
    console.log(`[VERIFIED] Found ${records.length} record(s) cryptographically signed by this publisher:`)
    
    records.forEach(record => {
      console.log(`  - Price: ${record.price}, Time: ${new Date(record.timestamp).toISOString()}`)
    })

  } catch (error: any) {
    console.error(`Error during verification: ${error.message}`)
  }
}

// --- Main Execution ---

async function main() {
  const sdk = new SDK({ public: publicClient })
  
  const schemaId = await sdk.streams.computeSchemaId(oraclePriceSchema)
  if (!schemaId) throw new Error('Could not compute schemaId')

  console.log('Starting Data Provenance Verification...')
  console.log(`Schema: oraclePriceSchema (${schemaId})`)

  // 1. Verify our trusted oracles
  for (const oracleAddress of TRUSTED_ORACLES) {
    await verifyPublisher(sdk, schemaId, oracleAddress)
  }

  // 2. Verify the imposter
  // This will securely return NO data, even if the imposter
  // published data to the same schemaId under their *own* address.
  await verifyPublisher(sdk, schemaId, IMPOSTER_ORACLE)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
```

### **Expected Output**

To run this, first publish some data (using the script from the previous tutorial, but adapted for `oraclePriceSchema`) from both `PUBLISHER_1_PK` and `PUBLISHER_2_PK`. Then, run the verification script.

```bash
# Add to package.json
"verify": "ts-node src/scripts/verifyOrigin.ts"

# Run it
npm run verify
```

You will see an output similar to this:

```bash
Starting Data Provenance Verification...
Schema: oraclePriceSchema (0x...)

--- Verifying Publisher: 0xPublisher1Address... ---
[VERIFIED] Found 2 record(s) cryptographically signed by this publisher:
  - Price: 3200, Time: 2025-10-31T12:30:00.000Z
  - Price: 3201, Time: 2025-10-31T12:31:00.000Z

--- Verifying Publisher: 0xPublisher2Address... ---
[VERIFIED] Found 1 record(s) cryptographically signed by this publisher:
  - Price: 3199, Time: 2025-10-31T12:30:30.000Z

--- Verifying Publisher: 0x1234567890123456789012345678901234567890 ---
[VERIFIED] No data found for this publisher.
```

## Conclusion: Key Takeaways

* **Provenance is Built-In:** Data provenance in Somnia Streams is not an optional feature; it is a core cryptographic guarantee of the `Streams` smart contract, enforced by `msg.sender`.
* **Verification is Implicit:** You verify data origin every time you perform a read operation with `getAllPublisherDataForSchema` or `getByKey`. The `publisher` address acts as the ultimate verification key.
* **Trust Layer:** This architecture creates a robust trust layer. Your application logic can be certain that any data returned for a specific publisher was, without question, signed and submitted by that publisher's wallet.


# SDK Methods Guide

Somnia Data Streams is the on-chain data streaming protocol that powers real-time, composable applications on the Somnia Network. It is available as an SDK Package [@somnia-chain/streams](https://www.npmjs.com/package/@somnia-chain/streams).

This SDK exposes all the core functionality developers need to write, read, subscribe to, and manage Data Streams and events directly from their dApps.

Before using the Data Streams SDK, ensure you have a working Node.js or Next.js environment (Node 18+ recommended). You’ll need access to a Somnia RPC endpoint (Testnet or Mainnet) and a wallet private key for publishing data.

### Installation

```bash
npm i @somnia-chain/streams viem dotenv
```

The SDK depends on [viem](https://viem.sh/) for blockchain interactions.

### Project Setup

Create a `.env.local` or `.env` file in your project root:

```bash
RPC_URL=https://dream-rpc.somnia.network
PRIVATE_KEY=your_private_key_here
```

⚠️ Never expose private keys in client-side code. Keep writes (publishing data) in server routes or backend environments.

### Basic Initialization

You’ll typically use two clients:

* A public client for reading and subscribing
* A wallet client for writing to the Somnia chain

```typescript
import { SDK } from '@somnia-chain/streams'
import { createPublicClient, createWalletClient, http } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { somniaTestnet } from 'viem/chains'

const rpcUrl = process.env.RPC_URL!
const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`)

const sdk = new SDK({
  public: createPublicClient({ chain: somniaTestnet, transport: http(rpcUrl) }),
  wallet: createWalletClient({ chain: somniaTestnet, account, transport: http(rpcUrl) })
})
```

### Somnia Data Streams

Data Streams in Somnia represent structured, verifiable data channels. Every piece of data conforms to a schema that defines its structure (e.g. `timestamp`, `content`, `sender`), and publishers can emit this data either as on-chain transactions or off-chain event notifications.

The SDK follows a simple pattern:

```typescript
const sdk = new SDK({
  public: getPublicClient(),  // for reading and subscriptions
  wallet: getWalletClient()   // for writing
})
```

You’ll interact primarily through the `sdk.streams` interface.

### Core Methods Overview

### Write

#### `set(d: DataStream[]): Promise<Hex | null>`

**Description**

Publishes one or more data streams to the Somnia blockchain. Each stream must specify a `schema ID`, a `unique ID`, and the `encoded payload`.

**Use Case**

When you want to store data on-chain in a standardized format (e.g., chat messages, sensor telemetry, or leaderboard updates).

**Example**

```typescript
const tx = await sdk.streams.set([
  { id: dataId, schemaId, data }
])
console.log('Data published with tx hash:', tx)
```

Always register your schema before calling `set()` ; otherwise, the transaction will revert.

#### `emitEvents(e: EventStream[]): Promise<Hex | Error | null>`

**Description**

Emits a registered Streams event without persisting new data. This is used for off-chain reactivity, triggering listeners subscribed via WebSocket.

**Example**

```typescript
await sdk.streams.emitEvents([
  {
    id: 'ChatMessage',
    argumentTopics: [topic],
    data: '0x' // optional encoded payload
  }
])
```

Common Use includes notifying subscribers when something happens, e.g., “new message sent” or “order filled”.

#### `setAndEmitEvents(d: DataStream[], e: EventStream[]): Promise<Hex | Error | null>`

**Description**

Performs an atomic on-chain operation that both writes data and emits a corresponding event. This ensures your data and notifications are always in sync.

**Example**

```typescript
await sdk.streams.setAndEmitEvents(
  [{ id: dataId, schemaId, data }],
  [{ id: 'ChatMessage', argumentTopics: [topic], data: '0x' }]
)
```

It is ideal for chat apps, game updates, or IoT streams — where data must be recorded and instantly broadcast.

### Manage

#### `registerDataSchemas(registrations: DataSchemaRegistration[], ignoreRegisteredSchemas?: boolean): Promise<Hex | Error | null>`

**Description**

Registers a new data schema on-chain. Schemas define the structure of your Streams data, like a table schema in a database. The optional `ignoreRegisteredSchemas` parameter allows skipping registration if the schema is already registered.

**Example**

```typescript
await sdk.streams.registerDataSchemas([
  {
    schemaName: "chat",
    schema: 'uint64 timestamp, string message, address sender',
    parentSchemaId: zeroBytes32 // root schema
  }
], true) // Optionally ignore if already registered
```

Register before writing any new data type. If you modify the schema structure later, register it again as a new schema version.

#### `registerEventSchemas(ids: string[], schemas: EventSchema[]): Promise<Hex | Error | null>`

**Description**

Registers event definitions that can later be emitted or subscribed to.

**Example**

```typescript
await sdk.streams.registerEventSchemas(
  ['ChatMessage'],
  [{
    params: [{ name: 'roomId', paramType: 'bytes32', isIndexed: true }],
    eventTopic: 'ChatMessage(bytes32 indexed roomId)'
  }]
)
```

Use before calling `emitEvents()` or `subscribe()` for a specific event.

#### `manageEventEmittersForRegisteredStreamsEvent(streamsEventId: string, emitter: Address, isEmitter: boolean): Promise<Hex | Error | null>`

**Description**

Grants or revokes permission for an address to emit a specific event.

**Example**

```typescript
await sdk.streams.manageEventEmittersForRegisteredStreamsEvent(
  'ChatMessage',
  '0x1234abcd...',
  true // allow this address to emit
)
```

Used for access control in multi-publisher systems.

### Read

#### `getByKey(schemaId: SchemaID, publisher: Address, key: Hex): Promise<Hex[] | SchemaDecodedItem[][] | null>`

**Description**

Retrieves data stored under a schema by its unique ID.

**Example**

```typescript
const msg = await sdk.streams.getByKey(schemaId, publisher, dataId)
console.log('Data:', msg)
```

An example includes fetching a specific record, e.g., “fetch message by message ID”.

#### `getAtIndex(schemaId: SchemaID, publisher: Address, idx: bigint): Promise<Hex[] | SchemaDecodedItem[][] | null>`

**Description**

Fetches the record at a given index (0-based).

**Example**

```typescript
const record = await sdk.streams.getAtIndex(schemaId, publisher, 0n)
```

It is useful for sequential datasets like logs or telemetry streams.

#### `getBetweenRange(schemaId: SchemaID, publisher: Address, startIndex: bigint, endIndex: bigint): Promise<Hex[] | SchemaDecodedItem[][] | Error | null>`

**Description**

Fetches records within a specified index range (0-based, inclusive start, exclusive end).

**Use Case**

Retrieving a batch of historical data, such as paginated logs or time-series entries.

**Example**

```typescript
const records = await sdk.streams.getBetweenRange(schemaId, publisher, 0n, 10n)
console.log('Records in range:', records)
```

#### `getAllPublisherDataForSchema(schemaReference: SchemaReference, publisher: Address): Promise<Hex[] | SchemaDecodedItem[][] | null>`

**Description**

Retrieves all data published by a specific address under a given schema.

**Use Case**

Fetching complete datasets for analysis or synchronization.

**Example**

```typescript
const allData = await sdk.streams.getAllPublisherDataForSchema(schemaReference, publisher)
console.log('All publisher data:', allData)
```

#### `getLastPublishedDataForSchema(schemaId: SchemaID, publisher: Address): Promise<Hex[] | SchemaDecodedItem[][] | null>`

**Description**

Retrieves the most recently published data under a schema by a publisher.

**Use Case**

Getting the latest update, such as the most recent sensor reading or message.

**Example**

```typescript
const latest = await sdk.streams.getLastPublishedDataForSchema(schemaId, publisher)
console.log('Latest data:', latest)
```

#### `totalPublisherDataForSchema(schemaId: SchemaID, publisher: Address): Promise<bigint | null>`

**Description**

Returns how many records a publisher has stored under a schema.

**Example**

```typescript
const total = await sdk.streams.totalPublisherDataForSchema(schemaId, publisher)
console.log(`Total entries: ${total}`)
```

#### `isDataSchemaRegistered(schemaId: SchemaID): Promise<boolean | null>`

**Description**

Checks if a schema exists on-chain.

**Example**

```typescript
const exists = await sdk.streams.isDataSchemaRegistered(schemaId)
if (!exists) console.log('Schema not found')
```

#### `parentSchemaId(schemaId: SchemaID): Promise<Hex | null>`

**Description**

Finds the parent schema of a given schema, if one exists.

**Example**

```typescript
const parent = await sdk.streams.parentSchemaId(schemaId)
console.log('Parent Schema ID:', parent)
```

#### `schemaIdToId(schemaId: SchemaID): Promise<string | null>`

**Description**

Converts a schema ID (Hex) to its corresponding string identifier.

**Use Case**

Mapping hashed IDs back to human-readable names for display or logging.

**Example**

```typescript
const id = await sdk.streams.schemaIdToId(schemaId)
console.log('Schema ID string:', id)
```

#### `idToSchemaId(id: string): Promise<Hex | null>`

**Description**

Converts a string identifier to its corresponding schema ID (Hex).

**Use Case**

Looking up hashed IDs from known names for queries.

**Example**

```typescript
const schemaId = await sdk.streams.idToSchemaId('chat')
console.log('Schema ID:', schemaId)
```

#### `getAllSchemas(): Promise<string[] | null>`

**Description**

Retrieves a list of all registered schema identifiers.

**Use Case**

Discovering available schemas in the protocol.

**Example**

```typescript
const schemas = await sdk.streams.getAllSchemas()
console.log('All schemas:', schemas)
```

#### `getEventSchemasById(ids: string[]): Promise<EventSchema[] | null>`

**Description**

Fetches event schema details for given identifiers.

**Use Case**

Inspecting registered event structures before subscribing or emitting.

**Example**

```typescript
const eventSchemas = await sdk.streams.getEventSchemasById(['ChatMessage'])
console.log('Event schemas:', eventSchemas)
```

#### `computeSchemaId(schema: string): Promise<Hex | null>`

**Description**

Computes the deterministic `schemaId` without registering it.

**Example**

```typescript
const schemaId = await sdk.streams.computeSchemaId('uint64 timestamp, string content')
```

#### `getSchemaFromSchemaId(schemaId: SchemaID): Promise<{ baseSchema: string, finalSchema: string, schemaId: Hex } | Error | null>`

**Description**

Request a schema given the schema id used for data publishing and let the SDK take care of schema extensions.

**Use Case**

Retrieving schema details, including the base schema and the final extended schema, for a given schema ID.

**Example**

```typescript
const schemaInfo = await sdk.streams.getSchemaFromSchemaId(schemaId)
console.log('Schema info:', schemaInfo)
```

### Helpers

#### `deserialiseRawData(rawData: Hex[], parentSchemaId: Hex, schemaLookup: { schema: string; schemaId: Hex; } | null): Promise<Hex[] | SchemaDecodedItem[][] | null>`

**Description**

Deserializes raw data using the provided schema information.

**Use Case**

Decoding fetched raw bytes into structured objects for application use.

**Example**

```typescript
const decoded = await sdk.streams.deserialiseRawData(rawData, parentSchemaId, schemaLookup)
console.log('Decoded data:', decoded)
```

### Subscribe

#### `subscribe(initParams: SubscriptionInitParams): Promise<{ subscriptionId: string, unsubscribe: () => void } | undefined>`

**Description**

Creates a real-time WebSocket subscription to a Streams event. Whenever the specified event fires, the SDK calls your `onData` callback — optionally including enriched data from on-chain calls.

**Parameters**

* `ethCalls`: Fixed set of ETH calls that must be executed before onData callback is triggered. Multicall3 is recommended. Can be an empty array.
* `context`: Event sourced selectors to be added to the data field of ETH calls, possible values: topic0, topic1, topic2, topic3, topic4, data and address.
* `onData`: Callback for a successful reactivity notification.
* `onError`: Callback for a failed attempt.
* `eventContractSource`: Optional but is the contract event source (any on Somnia) that will be emitting the logs specified by topicOverrides.
* `topicOverrides`: Optional but this argument is a filter applied to the subscription. Up to 4 bytes32 event topics can be supplied. By not defining, this is the equivalent of a wildcard subscription to all event topics
* `onlyPushChanges`: Whether the data should be pushed to the subscriber only if eth\_call results are different from the previous.

**Example**

```typescript
// Wildcard subscription to all events emitted by all contracts
await sdk.streams.subscribe({
    ethCalls: [], // No view calls
    onData: (data) => {}
})
```

**With `ethCalls`**

```typescript
import { toEventSelector } from "viem"
const transferSelector = toEventSelector({
    name: 'Transfer',
    type: 'event',
    inputs: [
      { type: 'address', indexed: true, name: 'from' },
      { type: 'address', indexed: true, name: 'to' },
      { type: 'uint256', indexed: false, name: 'value' }
    ]
  })

await sdk.streams.subscribe({
  topicOverrides: [
    transferSelector, // Topic 0 (Transfer event)
  ],
  ethCalls: [{
    to: '0xERC20Address',
    data: encodeFunctionData({
      abi: erc20Abi,
      functionName: 'balanceOf',
      args: ['0xUserAddress']
    })
  }],
  onData: (data) => console.log('Trade + balance data:', data)
})
```

Useful for off-chain reactivity: real-time dashboards, chat updates, live feeds, or notifications.

**Notes**

* Requires `createPublicClient({ transport: webSocket() })`
* Use `setAndEmitEvents()` on the publisher side to trigger matching subscriptions.

### Protocol

#### `getSomniaDataStreamsProtocolInfo(): Promise<GetSomniaDataStreamsProtocolInfoResponse | Error | null>`

**Description**

Retrieves information about the Somnia Data Streams protocol.

**Use Case**

Fetching protocol-level details, such as version or configuration.

**Example**

```typescript
const info = await sdk.streams.getSomniaDataStreamsProtocolInfo()
console.log('Protocol info:', info)
```

### Key Types Reference

| Type                     | Description                                                                                              |
| ------------------------ | -------------------------------------------------------------------------------------------------------- |
| `DataStream`             | `{ id: Hex, schemaId: Hex, data: Hex }` – Used with `set()` or `setAndEmitEvents()` .                    |
| `EventStream`            | `{ id: string, argumentTopics: Hex[], data: Hex }` – Used with `emitEvents()` and `setAndEmitEvents()` . |
| `DataSchemaRegistration` | `{ schemaName: string, schema: string, parentSchemaId: Hex }` – For `registerDataSchemas()` .            |
| `EventSchema`            | `{ params: EventParameter[], eventTopic: string }` – For `registerEventSchemas()` .                      |
| `EthCall`                | `{ to: Address, data: Hex }` – Defines on-chain calls for event enrichment.                              |

### Developer Tips

* Always compute your schema ID locally before deploying: `await sdk.streams.computeSchemaId(schema)`.
* For chat-like or telemetry apps, pair `setAndEmitEvents()` (write) with `subscribe()` (read).
* Use `zeroBytes32` for base schemas that don’t extend others.
* All write methods return transaction hashes, use `waitForTransactionReceipt()` to confirm.
* Data Streams focus on persistent, schema-based storage, while Event Streams enable reactive notifications; use them together for comprehensive applications.


# “Hello World” App

If you’ve ever wanted to see your data travel onchain in real time, this is the simplest way to begin. In this guide, we’ll build and run a Hello World Publisher and Subscriber using the Somnia Data Streams SDK. It demonstrates how to define a schema, publish onchain data, and read it in real time.

Somnia Data Streams enables developers to store, retrieve, and react to real-time blockchain data without needing to build indexers or manually poll the chain.

Each app works around three key ideas:

1. Schemas – define the data format.
2. Data IDs – uniquely identify each record.
3. Publishers – wallet addresses that own and post data.

Your app can write (“publish”) data using one account, and another app (or user) can “subscribe” to read or monitor that data stream. This “Hello World” project demonstrates exactly how that works.

## Prerequisites

Before you begin:

* Node.js 20+
* A Somnia Testnet wallet with STT test tokens
* `.env` file containing your wallet credentials

## Project Setup

Create a Project Directory and install dependencies [@somnia-chain/streams](https://www.npmjs.com/package/@somnia-chain/streams) and [viem](https://viem.sh/):

```bash
npm i @somnia-chain/streams viem dotenv
```

Now create a .env file to hold your test wallet’s private key:

```bash
PRIVATE_KEY=0xYOUR_PRIVATE_KEY
PUBLIC_KEY=0xYOUR_PUBLIC_ADDRESS
```

## Project Overview

The project contains four files:

| File           | Description                                         |
| -------------- | --------------------------------------------------- |
| publisher.js   | Sends “Hello World” messages to Somnia Data Streams |
| subscriber.js  | Reads and displays those messages                   |
| dream-chain.js | Configures the Somnia Dream testnet connection      |
| package.json   | Handles dependencies and npm scripts                |

## Network Configuration

The file `dream-chain.js` defines the blockchain network connection.

```javascript
const { defineChain } = require("viem");
const dreamChain = defineChain({
  id: 50312,
  name: "Somnia Dream",
  network: "somnia-dream",
  nativeCurrency: { name: "STT", symbol: "STT", decimals: 18 },
  rpcUrls: {
    default: { http: ["https://dream-rpc.somnia.network"] },
  },
});

module.exports = { dreamChain };

```

This allows both publisher and subscriber scripts to easily reference the same testnet environment.

## Hello World Publisher

The publisher connects to the blockchain, registers a schema if necessary, and sends a “Hello World” message every few seconds.

```javascript
const { SDK, SchemaEncoder, zeroBytes32 } = require("@somnia-chain/streams")
const { createPublicClient, http, createWalletClient, toHex } = require("viem")
const { privateKeyToAccount } = require("viem/accounts")
const { waitForTransactionReceipt } = require("viem/actions")
const { dreamChain } = require("./dream-chain")
require("dotenv").config()

async function main() {
  const publicClient = createPublicClient({ chain: dreamChain, transport: http() })
  const walletClient = createWalletClient({
    account: privateKeyToAccount(process.env.PRIVATE_KEY),
    chain: dreamChain,
    transport: http(),
  })

  const sdk = new SDK({ public: publicClient, wallet: walletClient })

  // 1️⃣ Define schema
  const helloSchema = `string message, uint256 timestamp, address sender`
  const schemaId = await sdk.streams.computeSchemaId(helloSchema)
  console.log("Schema ID:", schemaId)

  // 2️⃣ Safer schema registration
  const ignoreAlreadyRegistered = true

  try {
    const txHash = await sdk.streams.registerDataSchemas(
      [
        {
          schemaName: 'hello_world',
          schema: helloSchema,
          parentSchemaId: zeroBytes32
        },
      ],
      ignoreAlreadyRegistered
    )

    if (txHash) {
      await waitForTransactionReceipt(publicClient, { hash: txHash })
      console.log(`✅ Schema registered or confirmed, Tx: ${txHash}`)
    } else {
      console.log('ℹ️ Schema already registered — no action required.')
    }
  } catch (err) {
    // fallback: if the SDK doesn’t support the flag yet
    if (String(err).includes('SchemaAlreadyRegistered')) {
      console.log('⚠️ Schema already registered. Continuing...')
    } else {
      throw err
    }
  }

  // 3️⃣ Publish messages
  const encoder = new SchemaEncoder(helloSchema)
  let count = 0

  setInterval(async () => {
    count++
    const data = encoder.encodeData([
      { name: 'message', value: `Hello World #${count}`, type: 'string' },
      { name: 'timestamp', value: BigInt(Math.floor(Date.now() / 1000)), type: 'uint256' },
      { name: 'sender', value: walletClient.account.address, type: 'address' },
    ])

    const dataStreams = [{ id: toHex(`hello-${count}`, { size: 32 }), schemaId, data }]
    const tx = await sdk.streams.set(dataStreams)
    console.log(`✅ Published: Hello World #${count} (Tx: ${tx})`)
  }, 3000)
}

main()

```

This function connects to Somnia Dream Testnet using your wallet and computes the schema ID for the message structure. It then registers the schema if not already registered.\
The \`encodeData\` method encodes each message as a structured data packet, and it then publishes data to the chain using sdk.streams.set().

Each transaction is a verifiable, timestamped on-chain record.

***

## Hello World Subscriber

The subscriber listens for any messages published under the same schema and publisher address.\
It uses a simple polling mechanism, executed every 3 seconds, to fetch and decode updates.

```javascript
const { SDK, SchemaEncoder } = require("@somnia-chain/streams");
const { createPublicClient, http } = require("viem");
const { dreamChain } = require("./dream-chain");
require('dotenv').config();

async function main() {
  const publisherWallet = process.env.PUBLISHER_WALLET;
  const publicClient = createPublicClient({ chain: dreamChain, transport: http() });
  const sdk = new SDK({ public: publicClient });

  const helloSchema = `string message, uint256 timestamp, address sender`;
  const schemaId = await sdk.streams.computeSchemaId(helloSchema);

  const schemaEncoder = new SchemaEncoder(helloSchema);
  const result = new Set();

  setInterval(async () => {
    const allData = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisherWallet);
    for (const dataItem of allData) {
      const fields = dataItem.data ?? dataItem;
      let message = "", timestamp = "", sender = "";
      for (const field of fields) {
        const val = field.value?.value ?? field.value;
        if (field.name === "message") message = val;
        if (field.name === "timestamp") timestamp = val.toString();
        if (field.name === "sender") sender = val;
      }

      const id = `${timestamp}-${message}`;
      if (!result.has(id)) {
        result.add(id);
        console.log(`🆕 ${message} from ${sender} at ${new Date(Number(timestamp) * 1000).toLocaleTimeString()}`);
      }
    }
  }, 3000);
}

main();
```

This function computes the same Schema ID used by the publisher. It polls the blockchain for all messages from that publisher and decodes data according to the schema fields. Then, it displays any new messages with timestamps and sender addresses.

***

## Run the App

Run both scripts in separate terminals:

```bash
npm run publisher
```

and then

```bash
npm run subscriber
```

You’ll see Publisher Output:

```bash
Schema ID: 0x27c30fa6547c34518f2de6a268b29ac3b54e51c98f8d0ef6018bbec9153e9742
⚠️ Schema already registered. Continuing...
✅ Published: Hello World #1 (Tx: 0xf21ad71a6c7aa54c171ad38b79ef417e8488fd750ce00c1357918b7c7fa5c951)
✅ Published: Hello World #2 (Tx: 0xe999b0381ba9d937d85eb558fefe214fa4e572767c4e698c6e31588ff0e68f0a)
```

Subscriber Output

```bash
🆕 Hello World #2 from 0xb6e4fa6ff2873480590c68D9Aa991e5BB14Dbf03 at 2:24:04 PM
🆕 Hello World #3 from 0xb6e4fa6ff2873480590c68D9Aa991e5BB14Dbf03 at 2:24:07 PM
```

Congratulations 🎉 You’ve just published and read blockchain data using Somnia Data Streams!

This is the foundation for real-time decentralized apps, chat apps, dashboards, IoT feeds, leaderboards, and more.

***

## Conclusion

You’ve just learned how to:

* Define and compute a schema and schema ID
* Register it on the Somnia Testnet
* Publish and subscribe to on-chain structured data
* Decode and render blockchain messages in real time

This simple 'Hello World' app is your first step toward building real-time, decentralized applications on Somnia.

# Build Your First Schema

Before you can publish or read structured data on the Somnia Network using Somnia Data Streams, you must first define a Schema.\
A schema acts as the blueprint or data contract between your publisher and all subscribers who wish to interpret your data correctly.

In the Somnia Data Streams system, every schema is expressed as a canonical string. A strict, ordered list of fields with Solidity compatible types.

\
For example, a chat application schema:

```solidity
uint64 timestamp, bytes32 roomId, string content, string senderName, address sender
```

This simple definition:

* Establishes how data should be encoded and decoded on-chain.
* Produces a unique schemaId derived from its exact string representation.
* Enables multiple publishers and readers to exchange data consistently, without needing to redeploy contracts or agree on custom ABIs.

Each schema you define becomes a typed, reusable data model, similar to a table definition in a database or an ABI for events, but far simpler. Once created, schemas can be:

* Reused across many applications.
* Extended to create hierarchical data definitions (e.g., “GPS coordinates” → “Vehicle telemetry”).
* Versioned by creating new schemas when structure changes occur.<br>

This tutorial will walk you through building, registering, and validating your first schema step by step.

## Prerequisites

Before continuing, ensure you have the following:

1. Node.js 20+
2. TypeScript configured in your project
3. `.env.local` file for environment variables

   Add your credentials to .env.local:

   ```markup
   RPC_URL=https://dream-rpc.somnia.network
   PRIVATE_KEY=0xYOUR_FUNDED_PRIVATE_KEY
   ```
4. A Funded Testnet Account. You’ll need an address with test tokens on the Somnia Testnet to register schemas or publish data.<br>

NOTE: The Private Key is only required if connecting a Private Key via a Viem wallet account.\
\
Important: Never expose your private key to a client-side environment. Keep it in server scripts or backend environments only.

***

## What You’ll Build

In this tutorial, you will:

* Create a canonical schema string (your “data ABI”)
* Compute the schema ID
* Register your schema on-chain (idempotently)
* Validate your schema with a simple encode/decode test<br>

We’ll use a chat message schema as a running example:

```solidity
uint64 timestamp, bytes32 roomId, string content, string senderName, address sender
```

This schema represents a single chat message, which can be used later to build a full on-chain chat application.

***

## Project Setup

### Install dependencies

```bash
npm i @somnia-chain/streams viem
npm i -D @types/node
```

### Define Chain configuration

```typescript
// src/lib/chain.ts
import { defineChain } from 'viem'

export const somniaTestnet = defineChain({
  id: 50312,
  name: 'Somnia Testnet',
  network: 'somnia-testnet',
  nativeCurrency: { name: 'STT', symbol: 'STT', decimals: 18 },
  rpcUrls: {
    default: { http: ['https://dream-rpc.somnia.network'] },
    public:  { http: ['https://dream-rpc.somnia.network'] },
  },
})
```

### Set up your clients

```typescript
// src/lib/clients.ts
import { createPublicClient, createWalletClient, http } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { somniaTestnet } from './chain'

function need(key: 'RPC_URL' | 'PRIVATE_KEY') {
  const v = process.env[key]
  if (!v) throw new Error(`Missing ${key} in .env.local`)
  return v
}

export const publicClient = createPublicClient({
  chain: somniaTestnet,
  transport: http(need('RPC_URL')),
})

export const walletClient = createWalletClient({
  account: privateKeyToAccount(need('PRIVATE_KEY') as `0x${string}`),
  chain: somniaTestnet,
  transport: http(need('RPC_URL')),
})
```

***

## Define the Schema String

```typescript
// src/lib/chatSchema.ts
export const chatSchema =
  'uint64 timestamp, bytes32 roomId, string content, string senderName, address sender'
```

Field order matters, and ensure to always use Solidity-compatible types. It is important to keep the `string` fields short to minimize gas. Note that changing type or order creates a new schema ID.<br>

***

## Compute the schemaId

```typescript
// scripts/compute-schema-id.ts
import 'dotenv/config'
import { SDK } from '@somnia-chain/streams'
import { publicClient } from '../src/lib/clients'
import { chatSchema } from '../src/lib/chatSchema'

async function main() {
  const sdk = new SDK({ public: publicClient })
  const id = await sdk.streams.computeSchemaId(chatSchema)
  console.log('Schema ID:', id)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
```

The SDK computes a unique hash of the schema string. This `schemaId` is your permanent identifier. Anyone using the same schema string will derive the same ID *\[confirm with Vincent for correctness]*.<br>

***

## Register the Schema

Registration makes your schema discoverable and reusable by others. *\[confirm with Vincent for correctness]*.

```typescript
// scripts/register-schema.ts
import 'dotenv/config'
import { SDK, zeroBytes32 } from '@somnia-chain/streams'
import { publicClient, walletClient } from '../src/lib/clients'
import { chatSchema } from '../src/lib/chatSchema'
import { waitForTransactionReceipt } from 'viem/actions'

async function main() {
  const sdk = new SDK({ public: publicClient, wallet: walletClient })
  const id = await sdk.streams.computeSchemaId(chatSchema)

  const isRegistered = await sdk.streams.isSchemaRegistered(id)
  if (isRegistered) {
    console.log('Schema already registered.')
    return
  }

  const txHash = await sdk.streams.registerDataSchemas({ schemaName: "chat", schema: chatSchema })
  console.log('Register tx:', txHash)

  const receipt = await waitForTransactionReceipt(publicClient, { hash: txHash })
  console.log('Registered in block:', receipt.blockNumber)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
```

`isSchemaRegistered()` checks chain state. `registerSchema()` publishes the schema definition to Streams. Thus, the transaction is idempotent, meaning that it is safe to re-run.

***

## Encode and Decode a Sample Payload

Test your schema locally before publishing any data.

```typescript
// scripts/encode-decode.ts
import 'dotenv/config'
import { SchemaEncoder } from '@somnia-chain/streams'
import { toHex, type Hex } from 'viem'
import { chatSchema } from '../src/lib/chatSchema'

const encoder = new SchemaEncoder(chatSchema)

const encodedData: Hex = encoder.encodeData([
  { name: 'timestamp',  value: Date.now().toString(),     type: 'uint64' },
  { name: 'roomId',     value: toHex('general', { size: 32 }), type: 'bytes32' },
  { name: 'content',    value: 'Hello Somnia!',           type: 'string' },
  { name: 'senderName', value: 'Victory',                 type: 'string' },
  { name: 'sender',     value: '0x0000000000000000000000000000000000000001', type: 'address' },
])

console.log('Encoded:', encodedData)
console.log('Decoded:', encoder.decodeData(encodedData))
```

`encodeData()` serializes the payload according to the schema definition. `decodeData()` restores readable field values from the encoded hex. This step ensures your schema fields align correctly.

***

## Conclusion

You’ve just built and registered your first schema on Somnia Data Streams.

Your schema now acts as a public data contract between any publisher and subscriber that wants to communicate using this structure.<br>

# Streams Case Study: Formula 1

### Schemas

Driver schema

```
uint32 number, string name, string abbreviation, string teamName, string teamColor
```

Cartesian 3D coordinates schema

```
int256 x, int256 y, int256 z
```

The driver schema can extend the cartesian coordinates since the 3D coordinates will be used widely for other applications. Again this promotes re-usability of schemas.

### Schema registration and re-use

```javascript
const { SDK, zeroBytes32, SchemaEncoder } = require("@somnia-chain/streams");
const {
    createPublicClient,
    http,
    createWalletClient,
    toHex,
    defineChain,
} = require("viem");
const { privateKeyToAccount } = require("viem/accounts");

const dreamChain = defineChain({
  id: 50312,
  name: "Somnia Testnet",
  network: "testnet",
  nativeCurrency: {
    decimals: 18,
    name: "STT",
    symbol: "STT",
  },
  rpcUrls: {
    default: {
      http: [
        "https://dream-rpc.somnia.network",
      ],
    },
    public: {
      http: [
        "https://dream-rpc.somnia.network",
      ],
    },
  },
})

async function main() {
    // Connect to the blockchain to read data with the public client
    const publicClient = createPublicClient({
      chain: dreamChain,
      transport: http(),
    })

    const walletClient = createWalletClient({
      account: privateKeyToAccount(process.env.PRIVATE_KEY),
      chain: dreamChain,
      transport: http(),
    })

    // Connect to the SDK
    const sdk = new SDK({
      public: publicClient,
      wallet: walletClient,
    })

    // Setup the schemas
    const coordinatesSchema = `int256 x, int256 y, int256 z`
    const driverSchema = `uint32 number, string name, string abbreviation, string teamName, string teamColor`

    // Derive Etherbase schema metadata
    const coordinatesSchemaId = await sdk.streams.computeSchemaId(
      coordinatesSchema
    )
    if (!coordinatesSchemaId) {
      throw new Error("Unable to compute the schema ID for the coordinates schema")
    }

    const driverSchemaId = await sdk.streams.computeSchemaId(
      driverSchema
    )
    if (!driverSchemaId) {
      throw new Error("Unable to compute the schema ID for the driver schema")
    }

    const extendedSchema = `${driverSchema}, ${coordinatesSchema}`
    console.log("Schemas in use", {
      coordinatesSchemaId,
      driverSchemaId,
      coordinatesSchema,
      driverSchema,
      extendedSchema 
    })

    const isCoordinatesSchemaRegistered = await sdk.streams.isDataSchemaRegistered(coordinatesSchemaId)
    if (!isCoordinatesSchemaRegistered) {
      // We want to publish the driver schema but we need to publish the coordinates schema first before it can be extended
      const registerCoordinatesSchemaTxHash =
        await sdk.streams.registerDataSchemas([
          { schemaName: "coords", schema: coordinatesSchema }
        ])

      if (!registerCoordinatesSchemaTxHash) {
        throw new Error("Failed to register coordinates schema")
      }
      console.log("Registered coordinates schema on-chain", {
        registerCoordinatesSchemaTxHash
      })

      await publicClient.waitForTransactionReceipt({ 
        hash: registerCoordinatesSchemaTxHash
      })
    }

    const isDriverSchemaRegistered = await sdk.streams.isDataSchemaRegistered(driverSchemaId)
    if (!isDriverSchemaRegistered) {
      // Now, publish the driver schema but extend the coordinates schema!
      const registerDriverSchemaTxHash = sdk.streams.registerDataSchemas([
        { schemaName: "driver", schema: driverSchema, parentSchemaId: coordinatesSchemaId }
      ])
      if (!registerDriverSchemaTxHash) {
        throw new Error("Failed to register schema on-chain")
      }
      console.log("Registered driver schema on-chain", {
        registerDriverSchemaTxHash,
      })

      await publicClient.waitForTransactionReceipt({ 
        hash: registerDriverSchemaTxHash
      })
    }

    // Publish some data!! 
    const schemaEncoder = new SchemaEncoder(extendedSchema)
    const encodedData = schemaEncoder.encodeData([
        { name: "number", value: "44", type: "uint32" },
        { name: "name", value: "Lewis Hamilton", type: "string" },
        { name: "abbreviation", value: "HAM", type: "string" },
        { name: "teamName", value: "Ferrari", type: "string" },
        { name: "teamColor", value: "#F91536", type: "string" },
        { name: "x", value: "-1513", type: "int256" },
        { name: "y", value: "0", type: "int256" },
        { name: "z", value: "955", type: "int256" },
    ])
    console.log("encodedData", encodedData)

    const dataStreams = [{
      // Data id: DRIVER number - index will be a helpful lookup later and references ./data/f1-coordinates.js Cube 4 coordinates (driver 44) - F1 telemetry data
      id: toHex(`44-0`, { size: 32 }),
      schemaId: driverSchemaId,
      data: encodedData
    }]

    const publishTxHash = await sdk.streams.set(dataStreams)
    console.log("\nPublish Tx Hash", publishTxHash)
}
```

# READ Stream Data from a UI (Next.js Example)

In this guide, you’ll learn how to read data published to Somnia Data Streams directly from a Next.js frontend, the same way you’d use readContract with Viem.

We’ll build a simple HelloWorld schema and use it to demonstrate all the READ methods in the Somnia Data Streams SDK, from fetching the latest message to retrieving complete datasets or schema metadata.

***

## Prerequisites

Before we begin, make sure you have:

```bash
npm i @somnia-chain/streams viem
```

Also ensure:

* Node.js 20+
* A Somnia Testnet wallet with STT test tokens
* `.env` file containing your wallet credentials:
* A working Next.js app (npx create-next-app somnia-streams-read)
* Access to a publisher address and schema ID (or one you’ve created earlier)

***

## Set up the SDK and Client

We’ll initialize the SDK using Viem’s createPublicClient to communicate with Somnia’s blockchain.

```typescript
// lib/store.ts
import { SDK } from '@somnia-chain/streams'
import { createPublicClient, http } from 'viem'
import { somniaTestnet } from 'viem/chains'

const publicClient = createPublicClient({
  chain: somniaTestnet,
  transport: http(),
})

export const sdk = new SDK(publicClient)
```

This sets up the data-reading connection between your frontend and the Somnia testnet.

Think of it as the Streams version of [readContract()](https://viem.sh/docs/contract/readContract#readcontract); it lets you pull structured data (not just variables) directly from the blockchain.

***

## Define Schema and Publisher

A schema describes the structure of data stored in Streams, just like how a smart contract defines the structure of state variables.

```typescript
// lib/schema.ts
export const helloWorldSchema = 'uint64 timestamp, string message'
export const schemaId = '0xabc123...'   // Example Schema ID
export const publisher = '0xF9D3...E5aC' // Example Publisher Address
```

If you don’t have the schema ID handy, you can generate it from its definition:

```typescript
const computedId = await sdk.streams.computeSchemaId(helloWorldSchema)
console.log('Computed Schema ID:', computedId)
```

This ensures that you’re referencing the same schema ID under which the data was published.

***

## Fetch Latest “Hello World” Message

This is the most common use case: getting the most recent data point. For example, displaying the latest sensor reading or chat message.

```typescript
// lib/read.ts
import { sdk } from './store'
import { schemaId, publisher } from './schema'

export async function getLatestMessage() {
  const latest = await sdk.streams.getLastPublishedDataForSchema(schemaId, publisher)
  console.log('Latest data:', latest)
  return latest
}
```

This method retrieves the newest record from that schema-publisher combination.

It’s useful when:

* You’re showing a live dashboard
* You need real-time data polling
* You want to auto-refresh a view (e.g., “Last Updated at…”)

***

## Fetch by Key (e.g., message ID)

Each record can have a unique key, such as a message ID, sensor UUID, or user reference. When you know that key, you can fetch the exact record.

```typescript
export async function getMessageById(messageKey: `0x${string}`) {
  const msg = await sdk.streams.getByKey(schemaId, publisher, messageKey)
  console.log('Message by key:', msg)
  return msg
}
```

When to use:

* Fetching a message by its ID (e.g., “message #45a1”)
* Retrieving a transaction or sensor entry when you know its hash
* Building a detail view (e.g., /message/\[id] route in Next.js)

Think of it like calling readContract for one item by ID.

***

## Fetch by Index (Sequential Logs)

In sequential datasets such as logs, chat history, and telemetry, each record is indexed numerically.\
You can fetch a specific record by its position:

```typescript
export async function getMessageAtIndex(index: bigint) {
  const record = await sdk.streams.getAtIndex(schemaId, publisher, index)
  console.log(`Record at index ${index}:`, record)
  return record
}
```

When to use:

* When looping through entries in order (0, 1, 2, ...)
* To replay logs sequentially
* To test pagination logic

Example: getAtIndex(schemaId, publisher, 0n) retrieves the very first message.

***

## Fetch a Range of Records (Paginated View)

You can fetch multiple entries at once using index ranges.\
This is perfect for pagination or time-series queries.

```typescript
export async function getMessagesInRange(start: bigint, end: bigint) {
  const records = await sdk.streams.getBetweenRange(schemaId, publisher, start, end)
  console.log('Records in range:', records)
  return records
}
```

Example Use Cases:

* Displaying the last 10 chat messages: getBetweenRange(schemaId, publisher, 0n, 10n)
* Loading older telemetry data
* Implementing infinite scroll

Tip: Treat start and end like array indices (inclusive start, exclusive end).\
`start` is inclusive and `end` is exclusive.

***

## Fetch All Publisher Data for a Schema

If you want to retrieve all content a publisher has ever posted to a given schema, use this.

```typescript
export async function getAllPublisherData() {
  const allData = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisher)
  console.log('All publisher data:', allData)
  return allData
}
```

When to use:

* Generating analytics or trend charts
* Migrating or syncing full datasets
* Debugging data integrity or history<br>

You can think of this as:

“Give me the entire dataset under this schema from this publisher.”

It’s the Streams equivalent of querying all events from a contract.

This should be used for small data sets. For larger, paginated reading, `getBetweenRange` is recommended not to overwhelm the node returning the data.

***

## Count Total Entries

Sometimes, you just want to know how many entries exist.

```typescript
export async function getTotalEntries() {
  const total = await sdk.streams.totalPublisherDataForSchema(schemaId, publisher)
  console.log(`Total entries: ${total}`)
  return Number(total)
}
```

When to use:

* To know the total record count for pagination
* To display dataset stats (“42 entries recorded”)
* To monitor the growth of a stream

This helps determine boundaries for getBetweenRange() or detect when new data arrives.

***

## Inspect Schema Metadata

Schemas define structure, and sometimes you’ll want to validate or inspect them before reading data. First, check that a schema exists when publishing a new schema:

```typescript
  const ignoreAlreadyRegistered = true
  try {
    const txHash = await sdk.streams.registerDataSchemas(
      [
        {
          schemaName: 'hello_world',
          schema: helloSchema,
          parentSchemaId: zeroBytes32
        },
      ],
      ignoreAlreadyRegistered
    )

    if (txHash) {
      await waitForTransactionReceipt(publicClient, { hash: txHash })
      console.log(`Schema registered or confirmed, Tx: ${txHash}`)
    } else {
      console.log('Schema already registered — no action required.')
    }
  } catch (err) {
    // fallback: if the SDK doesn’t support the flag yet
    if (String(err).includes('SchemaAlreadyRegistered')) {
      console.log('Schema already registered. Continuing...')
    } else {
      throw err
    }
  }
```

This is critical to ensure your app doesn’t attempt to query a non-existent or unregistered schema — useful for user-facing dashboards.

***

## Retrieve Full Schema Information

```typescript
const schemaInfo = await sdk.streams.getSchemaFromSchemaId(schemaId)
console.log('Schema Info:', schemaInfo)
```

This method retrieves both the base schema and its extended structure, if any.\
It automatically resolves inherited schemas, so you get the full picture of what fields exist.

Example output:

```json
{
  baseSchema: 'uint64 timestamp, string message',
  finalSchema: 'uint64 timestamp, string message',
  schemaId: '0xabc123...'
}
```

This is important when you’re visualizing or decoding raw stream data, you can use the schema structure to parse fields correctly (timestamp, string, address, etc.).

***

## Example Next.js App

Now let’s render our fetched data in the UI.

### Project Setup

```bash
npx create-next-app somnia-streams-reader --typescript
cd somnia-streams-reader
npm install @somnia-chain/streams viem
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

***

### Folder Structure

```
somnia-streams-reader/
├── app/
│   ├── api/
│   │   └── latest/route.ts
│   ├── page.tsx
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── StreamViewer.tsx
│   └── SchemaInfo.tsx
├── lib/
│   ├── store.ts
│   ├── schema.ts
│   └── read.ts
├── tailwind.config.js
└── package.json
```

***

### lib/store.ts

Sets up the Somnia SDK and connects to the testnet.

```ts
import { SDK } from "@somnia-chain/streams"
import { createPublicClient, http } from "viem"
import { somniaTestnet } from "viem/chains"

const publicClient = createPublicClient({
  chain: somniaTestnet,
  transport: http(),
})

export const sdk = new SDK(publicClient)
```

***

### lib/schema.ts

Defines your schema and publisher.

```ts
export const helloWorldSchema = "uint64 timestamp, string message"
export const schemaId = "0xabc123..." // replace with actual schemaId
export const publisher = "0xF9D3...E5aC" // replace with actual publisher
```

If you don’t know your schema ID yet, you can compute it later using:

```ts
const computed = await sdk.streams.computeSchemaId(helloWorldSchema)
console.log("Schema ID:", computed)
```

***

### lib/read.ts

Implements read helpers for your API and UI.

```ts
import { sdk } from "./store"
import { schemaId, publisher } from "./schema"

export async function getLatestMessage() {
  return await sdk.streams.getLastPublishedDataForSchema(schemaId, publisher)
}

export async function getMessagesInRange(start: bigint, end: bigint) {
  return await sdk.streams.getBetweenRange(schemaId, publisher, start, end)
}

export async function getSchemaInfo() {
  return await sdk.streams.getSchemaFromSchemaId(schemaId)
}
```

***

### app/api/latest/route.ts

A serverless route to fetch the latest message (you can add more routes for range or schema info).

```ts
import { NextResponse } from "next/server"
import { getLatestMessage } from "@/lib/read"

export async function GET() {
  const data = await getLatestMessage()
  return NextResponse.json({ data })
}
```

***

### components/StreamViewer.tsx

A live component with interactive buttons for fetching data.

<details>

<summary>StreamViewer.tsx</summary>

```tsx
"use client"
import { useState } from "react"

export default function StreamViewer() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const fetchLatest = async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/latest")
      const { data } = await res.json()
      setData(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white shadow-md p-6 rounded-2xl border">
      <h2 className="text-xl font-semibold mb-4">HelloWorld Stream Reader</h2>

      <button
        onClick={fetchLatest}
        className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md"
        disabled={loading}
      >
        {loading ? "Loading..." : "Fetch Latest Message"}
      </button>

      {data && (
        <pre className="bg-gray-900 text-green-300 p-4 mt-4 rounded overflow-x-auto text-sm">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

</details>

***

### components/SchemaInfo.tsx

Displays the schema metadata.

```tsx
"use client"

import { useState } from "react"

export default function SchemaInfo() {
  const [info, setInfo] = useState<any>(null)

  const fetchInfo = async () => {
    const res = await fetch("/api/latest") // just for demo; replace with /api/schema if separate route
    const { data } = await res.json()
    setInfo(data)
  }

  return (
    <div className="bg-gray-50 p-6 rounded-xl shadow">
      <h2 className="font-semibold text-lg mb-3">Schema Information</h2>
      <button
        onClick={fetchInfo}
        className="bg-gray-800 text-white px-3 py-2 rounded-md"
      >
        Load Schema Info
      </button>
      {info && (
        <pre className="bg-black text-green-300 mt-3 p-3 rounded">
          {JSON.stringify(info, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

***

### app/page.tsx

Main dashboard combining both components.

```tsx
import StreamViewer from "@/components/StreamViewer"
import SchemaInfo from "@/components/SchemaInfo"

export default function Home() {
  return (
    <main className="p-10 min-h-screen bg-gray-100">
      <h1 className="text-3xl font-bold mb-8">🛰️ Somnia Data Streams Reader</h1>

      <div className="grid gap-6 md:grid-cols-2">
        <StreamViewer />
        <SchemaInfo />
      </div>
    </main>
  )
}
```

***

### app/layout.tsx

Wraps the layout globally.

```tsx
import "./globals.css"

export const metadata = {
  title: "Somnia Streams Reader",
  description: "Read on-chain data from Somnia Data Streams",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  )
}
```

***

### Run the App

```bash
npm run dev
```

Visit <http://localhost:3000> to open your dashboard.\
You’ll see a **“Fetch Latest Message”** button that retrieves data via `/api/latest` and a **Schema Info** section (ready to expand)

***

## Summary Table

| Method                        | Purpose                          | Example                                            |
| ----------------------------- | -------------------------------- | -------------------------------------------------- |
| getByKey                      | Fetch a record by unique ID      | getByKey(schemaId, publisher, dataId)              |
| getAtIndex                    | Fetch record at position         | getAtIndex(schemaId, publisher, 0n)                |
| getBetweenRange               | Retrieve records in range        | getBetweenRange(schemaId, publisher, 0n, 10n)      |
| getAllPublisherDataForSchema  | Fetch all data by publisher      | getAllPublisherDataForSchema(schemaRef, publisher) |
| getLastPublishedDataForSchema | Latest record only               | getLastPublishedDataForSchema(schemaId, publisher) |
| totalPublisherDataForSchema   | Count of entries                 | totalPublisherDataForSchema(schemaId, publisher)   |
| isDataSchemaRegistered        | Check if schema exists           | isDataSchemaRegistered(schemaId)                   |
| schemaIdToId / idToSchemaId   | Convert between Hex and readable | Useful for UI & schema mapping                     |
| getSchemaFromSchemaId         | Inspect full schema definition   | Retrieves base + extended schema                   |

<br>

# Integrate Chainlink Oracles

Somnia Data Streams provides a powerful, on-chain, and composable storage layer. [Chainlink Oracles](https://docs.chain.link/data-feeds/price-feeds/addresses?page=1\&testnetPage=1\&networkType=testnet\&search=\&testnetSearch=) provide secure, reliable, and decentralized external data feeds.

When you combine them, you unlock a powerful new capability: **creating historical, queryable, on-chain data streams from real-world data.**

Chainlink Price Feeds are designed to provide the *latest* price of an asset. They are not designed to provide a queryable history. You cannot easily ask a Price Feed, "What was the price of ETH 48 hours ago?"

By integrating Chainlink with Somnia Streams, you can build a "snapshot bot" that reads from Chainlink at regular intervals and appends the price to a Somnia Data Stream. This creates a permanent, verifiable, and historical on-chain feed that any other DApp or user can read and trust.

## **Objectives & Deliverable**

* **Objective:** Fetch off-chain data (a price feed) with Chainlink and store it historically via Somnia Streams.
* **Key Takeaway:** Combining external "truth" sources with Somnia's composable storage to create new, valuable on-chain data products.
* **Deliverable:** A hybrid "Snapshot Bot" that reads from Chainlink on the Sepolia testnet and publishes to a historical price feed on the Somnia Testnet.

## What You'll Build

1. **A New Schema:** A `priceFeedSchema` to store price data.
2. **A Chainlink Reader:** A script using `viem` to read the `latestRoundData` from Chainlink's ETH/USD feed on the Sepolia testnet.
3. **A Snapshot Bot:** A script that reads from Chainlink (Sepolia) and writes to Somnia Data Streams (Somnia Testnet).
4. **A History Reader:** A script to read our new historical price feed from Somnia Data Streams.

This tutorial demonstrates a true hybrid-chain application.

## Prerequisites

* Node.js 20+.
* `@somnia-chain/streams`, `viem`, and `dotenv` installed.
* A wallet with Somnia Testnet tokens (for publishing) and Sepolia testnet ETH (for gas, though we are only reading, so a public RPC is fine).

## **Environment Setup**

Create a `.env` file. You will need RPC URLs for **both** chains and a private key for the Somnia Testnet (to pay for publishing).

```bash
# .env
RPC_URL_SOMNIA=[https://dream-rpc.somnia.network]
RPC_URL_SEPOLIA=[https://sepolia.drpc.org]
PRIVATE_KEY_SOMNIA=0xYOUR_SOMNIA_PRIVATE_KEY
```

## Project Setup

Set up your project with `viem` and the Streams SDK.

```bash
npm i @somnia-chain/streams viem dotenv
npm i -D @types/node typescript ts-node
```

## **Chain Configuration**

We need to define both chains we are interacting with.

**`src/lib/chain.ts`**

```typescript
import { defineChain } from 'viem'
import { sepolia as sepoliaBase } from 'viem/chains'

// 1. Somnia Testnet
export const somniaTestnet = defineChain({
  id: 50312,
  name: 'Somnia Testnet',
  network: 'somnia-testnet',
  nativeCurrency: { name: 'STT', symbol: 'STT', decimals: 18 },
  rpcUrls: {
    default: { http: [process.env.RPC_URL_SOMNIA || ''] },
    public:  { http: [process.env.RPC_URL_SOMNIA || ''] },
  },
} as const)

// 2. Sepolia Testnet (for Chainlink)
export const sepolia = sepoliaBase
```

## **Client Configuration**

We will create two separate clients:

* A **Somnia SDK client** (with a wallet) to *write* data.
* A **Sepolia Public Client** (read-only) to *read* from Chainlink.

**`src/lib/clients.ts`**

```typescript
import 'dotenv/config'
import { createPublicClient, createWalletClient, http } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { SDK } from '@somnia-chain/streams'
import { somniaTestnet, sepolia } from './chain'

function getEnv(key: string): string {
  const value = process.env[key]
  if (!value) throw new Error(`Missing environment variable: ${key}`)
  return value
}

// === Client 1: Somnia SDK (Read/Write) ===
const somniaWalletClient = createWalletClient({
  account: privateKeyToAccount(getEnv('PRIVATE_KEY_SOMNIA') as `0x${string}`),
  chain: somniaTestnet,
  transport: http(getEnv('RPC_URL_SOMNIA')),
})

const somniaPublicClient = createPublicClient({
  chain: somniaTestnet,
  transport: http(getEnv('RPC_URL_SOMNIA')),
})

export const somniaSdk = new SDK({
  public: somniaPublicClient,
  wallet: somniaWalletClient,
})

// === Client 2: Sepolia Public Client (Read-Only) ===
export const sepoliaPublicClient = createPublicClient({
  chain: sepolia,
  transport: http(getEnv('RPC_URL_SEPOLIA')),
})
```

## Define the Price Feed Schema

Our schema will store the core data from Chainlink's feed.

**`src/lib/schema.ts`**

```typescript
// This schema will store historical price snapshots
export const priceFeedSchema = 
  'uint64 timestamp, int256 price, uint80 roundId, string pair'
```

* `timestamp`: The `updatedAt` time from Chainlink.
* `price`: The `answer` (e.g., ETH price).
* `roundId`: The Chainlink round ID, to prevent duplicates.
* `pair`: A string to identify the feed (e.g., "ETH/USD").

## Create the Chainlink Reader

Let's create a dedicated file to handle fetching data from Chainlink. We will use the `ETH/USD` feed on Sepolia.

**`src/lib/chainlinkReader.ts`**

```typescript
import { parseAbi, Address } from 'viem'
import { sepoliaPublicClient } from './clients'

// Chainlink ETH/USD Feed on Sepolia Testnet
const CHAINLINK_FEED_ADDRESS: Address = '0x694AA1769357215DE4FAC081bf1f309aDC325306'

// Minimal ABI for AggregatorV3Interface
const CHAINLINK_ABI = parseAbi([
  'function latestRoundData() external view returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)',
  'function decimals() external view returns (uint8)',
])

export interface PriceData {
  roundId: bigint
  price: bigint
  timestamp: bigint
  decimals: number
}

/**
 * Fetches the latest price data from the Chainlink ETH/USD feed on Sepolia.
 */
export async function fetchLatestPrice(): Promise<PriceData> {
  console.log('Fetching latest price from Chainlink on Sepolia...')
  
  try {
    const [roundData, decimals] = await Promise.all([
      sepoliaPublicClient.readContract({
        address: CHAINLINK_FEED_ADDRESS,
        abi: CHAINLINK_ABI,
        functionName: 'latestRoundData',
      }),
      sepoliaPublicClient.readContract({
        address: CHAINLINK_FEED_ADDRESS,
        abi: CHAINLINK_ABI,
        functionName: 'decimals',
      })
    ])

    const [roundId, answer, , updatedAt] = roundData
    
    console.log(`Chainlink data received: Round ${roundId}, Price ${answer}`)
    
    return {
      roundId,
      price: answer,
      timestamp: updatedAt,
      decimals,
    }
  } catch (error: any) {
    console.error(`Failed to read from Chainlink: ${error.message}`)
    throw error
  }
}
```

## Build the Snapshot Bot (The Hybrid App)

This is the core of our project. This script will:

1. Fetch the latest price from Chainlink (using our module).
2. Encode this data using our `priceFeedSchema`.
3. Publish the data to Somnia Data Streams.

**`src/scripts/snapshotBot.ts`**

<pre class="language-typescript"><code class="lang-typescript">import 'dotenv/config'
import { somniaSdk } from '../lib/clients'
import { priceFeedSchema } from '../lib/schema'
import { fetchLatestPrice } from '../lib/chainlinkReader'
import { SchemaEncoder, zeroBytes32 } from '@somnia-chain/streams'
import { toHex, Hex } from 'viem'
import { waitForTransactionReceipt } from 'viem/actions'

const PAIR_NAME = "ETH/USD"

async function main() {
  console.log('--- Starting Snapshot Bot ---')
  
  // 1. Initialize SDK and Encoder
  const sdk = somniaSdk
  const encoder = new SchemaEncoder(priceFeedSchema)
  const publisherAddress = sdk.wallet.account?.address
  if (!publisherAddress) throw new Error('Wallet client not initialized.')

  // 2. Compute Schema ID and Register (idempotent)
  const schemaId = await sdk.streams.computeSchemaId(priceFeedSchema)
  if (!schemaId) throw new Error('Could not compute schemaId')
  
  const ignoreAlreadyRegisteredSchemas = true
<strong>  const regTx = await sdk.streams.registerDataSchemas([
</strong>        { id: 'price-feed-v1', schema: priceFeedSchema }
    ], ignoreAlreadyRegisteredSchemas)
    if (!regTx) throw new Error('Failed to register schema')
    await waitForTransactionReceipt(sdk.public, { hash: regTx })

  // 3. Fetch data from Chainlink
  const priceData = await fetchLatestPrice()

  // 4. Encode data for Somnia Streams
  const encodedData: Hex = encoder.encodeData([
    { name: 'timestamp', value: priceData.timestamp.toString(), type: 'uint64' },
    { name: 'price', value: priceData.price.toString(), type: 'int256' },
    { name: 'roundId', value: priceData.roundId.toString(), type: 'uint80' },
    { name: 'pair', value: PAIR_NAME, type: 'string' },
  ])

  // 5. Create a unique Data ID (using the roundId to prevent duplicates)
  const dataId = toHex(`price-${PAIR_NAME}-${priceData.roundId}`, { size: 32 })

  // 6. Publish to Somnia Data Streams
  console.log(`Publishing price data to Somnia Streams...`)
  const txHash = await sdk.streams.set([
    { id: dataId, schemaId, data: encodedData }
  ])

  if (!txHash) throw new Error('Failed to publish to Streams')
  
  await waitForTransactionReceipt(sdk.public, { hash: txHash })
  
  console.log('\n--- Snapshot Complete! ---')
  console.log(`  Publisher: ${publisherAddress}`)
  console.log(`  Schema ID: ${schemaId}`)
  console.log(`  Data ID: ${dataId}`)
  console.log(`  Tx Hash: ${txHash}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
</code></pre>

**To run your bot:**

Add a script to `package.json`: `"snapshot": "ts-node src/scripts/snapshotBot.ts"`

Run it: `npm run snapshot`

You can run this script multiple times. It will only add new data if Chainlink's `roundId` has changed.

## Read Your Historical Price Feed

Now for the payoff. Let's create a script that reads our new on-chain history from Somnia Streams.

**`src/scripts/readHistory.ts`**

```typescript
import 'dotenv/config'
import { somniaSdk } from '../lib/clients'
import { priceFeedSchema } from '../lib/schema'
import { SchemaDecodedItem } from '@somnia-chain/streams'

// Helper to decode the SDK's output
interface PriceRecord {
  timestamp: number
  price: bigint
  roundId: bigint
  pair: string
}

function decodePriceRecord(row: SchemaDecodedItem[]): PriceRecord {
  const val = (field: any) => field?.value?.value ?? field?.value ?? ''
  return {
    timestamp: Number(val(row[0])),
    price: BigInt(val(row[1])),
    roundId: BigInt(val(row[2])),
    pair: String(val(row[3])),
  }
}

async function main() {
  console.log('--- Reading Historical Price Feed from Somnia Streams ---')
  const sdk = somniaSdk
  
  // Use the *publisher address* from your .env file
  const publisherAddress = sdk.wallet.account?.address
  if (!publisherAddress) throw new Error('Wallet client not initialized.')

  const schemaId = await sdk.streams.computeSchemaId(priceFeedSchema)
  if (!schemaId) throw new Error('Could not compute schemaId')

  console.log(`Reading all data for publisher: ${publisherAddress}`)
  console.log(`Schema: ${schemaId}\n`)

  // Fetch all data for this schema and publisher
  const data = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisherAddress)

  if (!data || data.length === 0) {
    console.log('No price history found. Run the snapshot bot first.')
    return
  }

  const records = (data as SchemaDecodedItem[][]).map(decodePriceRecord)
  
  // Sort by timestamp
  records.sort((a, b) => a.timestamp - b.timestamp)

  console.log(`Found ${records.length} historical price points:\n`)
  
  records.forEach(record => {
    // We assume the decimals are 8 for this ETH/USD feed
    const priceFloat = Number(record.price) / 10**8
    console.log(
      `[${new Date(record.timestamp * 1000).toISOString()}] ${record.pair} - $${priceFloat.toFixed(2)} (Round: ${record.roundId})`
    )
  })
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
```

**To read the history:**

Add to `package.json`: `"history": "ts-node src/scripts/readHistory.ts"`

Run it: `npm run history`

**Expected Output:**

```bash
--- Reading Historical Price Feed from Somnia Streams ---
...
Found 3 historical price points:

[2025-11-06T14:30:00.000Z] ETH/USD - $3344.50 (Round: 110...)
[2025-11-06T14:35:00.000Z] ETH/USD - $3362.12 (Round: 111...)
[2025-11-06T14:40:00.000Z] ETH/USD - $3343.90 (Round: 112...)
```

## Conclusion: Key Takeaways

You have successfully built a hybrid, cross-chain application.

* You combined an **external "truth source"** (Chainlink) with Somnia's **composable storage layer** (Somnia Data Streams).
* You created a new, valuable, on-chain data product: a **historical, queryable price feed** that any dApp on Somnia can now read from and trust.
* You demonstrated the power of the `publisher` address as a verifiable source. Any dApp can now consume your feed, knowing it was published by *your* trusted bot.

This pattern can be extended to any external data source: weather, sports results, IoT data, and more. You can run the `snapshotBot.ts` script as a cron job or serverless function to create a truly autonomous, on-chain oracle.


# Working with Multiple Publishers in a Shared Stream

The core architecture of Somnia Data Streams decouples data schemas from publishers. This allows multiple different accounts (or devices) to publish data using the **same schema**. The data conforms to the same data structure, regardless of who published it.

This model is perfect for multi-source data scenarios, such as:

* **Multi-User Chat:** Multiple users sending messages under the same `chatMessage` schema.
* **IoT (Internet of Things):** Hundreds of sensors submitting data under the same `telemetry` schema.
* **Gaming:** All players in a game publishing their positions and scores under the same `playerUpdate` schema.

In this tutorial, we will demonstrate how to build an "aggregator" application that collects and merges data from two different "devices" (two separate wallet accounts) publishing to the same "telemetry" schema.

## Prerequisites

* Node.js 20+
* `@somnia-chain/streams` and `viem` libraries installed
* An `RPC_URL` for access to the Somnia Testnet
* **Two (2)** funded Somnia Testnet wallets for publishing data.

## What You’ll Build

In this tutorial, we will build two main components:

1. A **Publisher Script** that simulates two different wallets sending data to the same telemetry schema.
2. An **Aggregator Script** that fetches *all* data from a specified list of publishers, merges them into a single list, and sorts them by timestamp.

## Project Setup

Create a new directory for your application and install the necessary packages.

```bash
mkdir somnia-aggregator
cd somnia-aggregator
npm init -y
npm i @somnia-chain/streams viem dotenv
npm i -D @types/node typescript ts-node
```

Create a `tsconfig.json` file in your project root:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "outDir": "./dist"
  },
  "include": ["src/**/*"]
}
```

## Configure Environment Variables

Create a `.env` file in your project root. For this tutorial, we will need **two** different private keys.

```bash
# .env
RPC_URL=https://dream-rpc.somnia.network/ 

# Simulates two different devices/publishers
PUBLISHER_1_PK=0xPUBLISHER_ONE_PRIVATE_KEY
PUBLISHER_2_PK=0xPUBLISHER_TWO_PRIVATE_KEY
```

**IMPORTANT:** Never expose private keys in client-side (browser) code or public repositories. The scripts in this tutorial are intended to be run server-side.

## Chain and Client Configuration

Create a folder named `src/lib` and set up your `chain.ts` and `clients.ts` files.

**`src/lib/chain.ts`**

```typescript
import { defineChain } from 'viem'

export const somniaTestnet = defineChain({
  id: 50312,
  name: 'Somnia Testnet',
  network: 'somnia-testnet',
  nativeCurrency: { name: 'STT', symbol: 'STT', decimals: 18 },
  rpcUrls: {
    default: { http: ['[https://dream-rpc.somnia.network]'] },
    public:  { http: ['[https://dream-rpc.somnia.network]'] },
  },
} as const)
```

**`src/lib/clients.ts`**

```typescript
import 'dotenv/config'
import { createPublicClient, createWalletClient, http, PublicClient } from 'viem'
import { privateKeyToAccount, PrivateKeyAccount } from 'viem/accounts'
import { somniaTestnet } from './chain'

function getEnv(key: string): string {
  const value = process.env[key]
  if (!value) {
    throw new Error(`Missing environment variable: ${key}`)
  }
  return value
}

// A single Public Client for read operations
export const publicClient: PublicClient = createPublicClient({
  chain: somniaTestnet, 
  transport: http(getEnv('RPC_URL')),
})

// Two different Wallet Clients for simulation
export const walletClient1 = createWalletClient({
  account: privateKeyToAccount(getEnv('PUBLISHER_1_PK') as `0x${string}`),
  chain: somniaTestnet, 
  transport: http(getEnv('RPC_URL')),
})

export const walletClient2 = createWalletClient({
  account: privateKeyToAccount(getEnv('PUBLISHER_2_PK') as `0x${string}`),
  chain: somniaTestnet,
  transport: http(getEnv('RPC_URL')),
})
```

## Define the Shared Schema

Let's define the common schema that all publishers will use.

**`src/lib/schema.ts`**

```typescript
// This schema will be used by multiple devices
export const telemetrySchema = 
  'uint64 timestamp, string deviceId, int32 x, int32 y, uint32 speed'
```

## Create the Publisher Script

Now, let's create a script that simulates how two different publishers will send data to this schema. This script will take which publisher to use as a command-line argument.

**`src/scripts/publishData.ts`**

```typescript
import 'dotenv/config'
import { SDK, SchemaEncoder, zeroBytes32 } from '@somnia-chain/streams'
import { publicClient, walletClient1, walletClient2 } from '../lib/clients'
import { telemetrySchema } from '../lib/schema'
import { toHex, Hex, WalletClient } from 'viem'
import { waitForTransactionReceipt } from 'viem/actions'

// Select which publisher to use
async function getPublisher(): Promise<{ client: WalletClient, deviceId: string }> {
  const arg = process.argv[2] // 'p1' or 'p2'
  if (arg === 'p2') {
    console.log('Using Publisher 2 (Device B)')
    return { client: walletClient2, deviceId: 'device-b-002' }
  }
  console.log('Using Publisher 1 (Device A)')
  return { client: walletClient1, deviceId: 'device-a-001' }
}

// Helper function to encode the data
function encodeTelemetry(encoder: SchemaEncoder, deviceId: string): Hex {
  const now = Date.now().toString()
  return encoder.encodeData([
    { name: "timestamp", value: now, type: "uint64" },
    { name: "deviceId", value: deviceId, type: "string" },
    { name: "x", value: Math.floor(Math.random() * 1000).toString(), type: "int32" },
    { name: "y", value: Math.floor(Math.random() * 1000).toString(), type: "int32" },
    { name: "speed", value: Math.floor(Math.random() * 120).toString(), type: "uint32" },
  ])
}

async function main() {
  const { client, deviceId } = await getPublisher()
  const publisherAddress = client.account.address
  console.log(`Publisher Address: ${publisherAddress}`)

  const sdk = new SDK({ public: publicClient, wallet: client })
  const encoder = new SchemaEncoder(telemetrySchema)

  // 1. Compute the Schema ID
  const schemaId = await sdk.streams.computeSchemaId(telemetrySchema)
  if (!schemaId) throw new Error('Could not compute schemaId')
  console.log(`Schema ID: ${schemaId}`)

  // 2. Register Schema (Updated for new API)
  console.log('Registering schema (if not already registered)...')
  
  const ignoreAlreadyRegisteredSchemas = true
  const regTx = await sdk.streams.registerDataSchemas([
    { 
      schemaName: 'telemetry', // Updated: 'id' is now 'schemaName'
      schema: telemetrySchema, 
      parentSchemaId: zeroBytes32 
    }
  ], ignoreAlreadyRegisteredSchemas)

  if (regTx) {
    console.log('Schema registration transaction sent:', regTx)
    await waitForTransactionReceipt(publicClient, { hash: regTx })
    console.log('Schema registered successfully!')
  } else {
    console.log('Schema was already registered. No transaction sent.')
  }

  // 3. Encode the data
  const encodedData = encodeTelemetry(encoder, deviceId)
  
  // 4. Publish the data
  // We make the dataId unique with a timestamp and device ID
  const dataId = toHex(`${deviceId}-${Date.now()}`, { size: 32 })
  
  const txHash = await sdk.streams.set([
    { id: dataId, schemaId, data: encodedData }
  ])

  if (!txHash) throw new Error('Failed to publish data')
  console.log(`Publishing data... Tx: ${txHash}`)

  await waitForTransactionReceipt(publicClient, { hash: txHash })
  console.log('Data published successfully!')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
```

**To run this script:**

Add the following scripts to your `package.json` file:

```json
"scripts": {
  "publish:p1": "ts-node src/scripts/publishData.ts p1",
  "publish:p2": "ts-node src/scripts/publishData.ts p2"
}
```

Now, open two different terminals and send data from each:

```bash
# Terminal 1
npm run publish:p1
# Terminal 2
npm run publish:p2
```

Repeat this a few times to build up a dataset from both publishers.

## Create the Aggregator Script

Now that we have published our data, we can write the "aggregator" script that collects, merges, and sorts all data from these two (or more) publishers.

**`src/scripts/aggregateData.ts`**

```typescript
import 'dotenv/config'
import { SDK, SchemaDecodedItem } from '@somnia-chain/streams'
import { publicClient, walletClient1, walletClient2 } from '../lib/clients'
import { telemetrySchema } from '../lib/schema'
import { Address } from 'viem'

// LIST OF PUBLISHERS TO TRACK
// You could also fetch this list dynamically (e.g., from a contract or database).
const TRACKED_PUBLISHERS: Address[] = [
  walletClient1.account.address,
  walletClient2.account.address,
]

// Helper function to convert SDK data into a cleaner object
// (Similar to the 'val' function in the Minimal On-Chain Chat App Tutorial)
function decodeTelemetryRecord(row: SchemaDecodedItem[]): TelemetryRecord {
  const val = (field: any) => field?.value?.value ?? field?.value ?? ''
  return {
    timestamp: Number(val(row[0])),
    deviceId: String(val(row[1])),
    x: Number(val(row[2])),
    y: Number(val(row[3])),
    speed: Number(val(row[4])),
  }
}

// Type definition for our data
interface TelemetryRecord {
  timestamp: number
  deviceId: string
  x: number
  y: number
  speed: number
  publisher?: Address // We will add this field later
}

async function main() {
  // The aggregator doesn't need to write data, so it only uses the publicClient
  const sdk = new SDK({ public: publicClient })
  
  const schemaId = await sdk.streams.computeSchemaId(telemetrySchema)
  if (!schemaId) throw new Error('Could not compute schemaId')

  console.log(`Aggregator started. Tracking ${TRACKED_PUBLISHERS.length} publishers...`)
  console.log(`Schema ID: ${schemaId}\n`)

  const allRecords: TelemetryRecord[] = []

  // 1. Loop through each publisher
  for (const publisherAddress of TRACKED_PUBLISHERS) {
    console.log(`--- Fetching data for ${publisherAddress} ---`)
    
    // 2. Fetch all data for the publisher based on the schema
    // Note: The SDK automatically decodes the data if the schema is registered
    const data = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisherAddress)
    
    if (!data || data.length === 0) {
      console.log('No data found for this publisher.\n')
      continue
    }

    // 3. Transform the data and add the 'publisher' field
    const records: TelemetryRecord[] = (data as SchemaDecodedItem[][]).map(row => ({
      ...decodeTelemetryRecord(row),
      publisher: publisherAddress // To know where the data came from
    }))

    console.log(`Found ${records.length} records.`)

    // 4. Add all records to the main list
    allRecords.push(...records)
  }

  // 5. Sort all data by timestamp
  console.log('\n--- Aggregation Complete ---')
  console.log(`Total records fetched: ${allRecords.length}`)

  allRecords.sort((a, b) => a.timestamp - b.timestamp)

  // 6. Display the result
  console.log('\n--- Combined and Sorted Telemetry Log ---')
  allRecords.forEach(record => {
    console.log(
      `[${new Date(record.timestamp).toISOString()}] [${record.publisher}] - Device: ${record.deviceId}, Speed: ${record.speed}`
    )
  })
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
```

**To run this script:**

Add the script to your `package.json` file:

```json
"scripts": {
  "publish:p1": "ts-node src/scripts/publishData.ts p1",
  "publish:p2": "ts-node src/scripts/publishData.ts p2",
  "aggregate": "ts-node src/scripts/aggregateData.ts"
}
```

And run it:

```bash
npm run aggregate
```

## Conclusion

In this tutorial, you learned how to manage a multi-publisher architecture with Somnia Data Streams.

* **Publisher Side:** The logic remained unchanged. Each publisher independently published its data using its wallet and the `sdk.streams.set()` method.
* **Aggregator Side:** This is where the main logic came in.
  1. We maintained a list of publishers we were interested in.
  2. We fetched the data for each publisher separately using the `getAllPublisherDataForSchema` method.
  3. We combined the incoming data into a single array (`allRecords.push(...)`).
  4. Finally, we sorted all the data on the client-side to display them in a meaningful order (e.g., by timestamp).

This pattern can be scaled to support any number of publishers and provides a robust foundation for building decentralized, multi-source applications.


# The DApp Publisher Proxy Pattern

In the "[Working with Multiple Publishers](https://www.google.com/search?q=httpsa://emre-gitbook.gitbook.io/emre-gitbook-docs/data-streams/working-with-multiple-publishers-in-a-shared-stream)" tutorial, you learned the standard pattern for building an aggregator:

1. Maintain a list of all known publisher addresses.
2. Loop through this list.
3. Call `sdk.streams.getAllPublisherDataForSchema()` for each address.
4. Merge and sort the results on the client side.

This pattern is simple and effective for a known, manageable number of publishers (e.g., 50 IoT sensors from a single company).

**But what happens at a massive scale?**

## The Problem: The 10,000-Publisher Scenario

Imagine you are building a popular on-chain game. You have a `leaderboardSchema` and 10,000 players actively publishing their scores.

If you use the standard aggregator pattern, your "global leaderboard" DApp would need to:

1. Somehow find all 10,000 player addresses.
2. Perform **10,000 separate read calls** (`getAllPublisherDataForSchema`) to the Somnia RPC node.

This is not scalable, fast, or efficient. It creates an enormous (and slow) data-fetching burden on your application.

## The Solution: The DApp Publisher Proxy

This is an advanced architecture that inverts the model to solve the read-scalability problem.

Instead of having 10,000 publishers write to Streams *directly*, they all write to **your DApp's smart contract**, which then publishes to Streams on their behalf.

**The Flow:**

1. **User (Publisher):** Calls a function on your DApp's contract (e.g., `myGame.submitScore(100)`). The `msg.sender` is the user's address.
2. **DApp Contract (The Proxy):** Internally, your `submitScore` function:
   * Adds the user's address (`msg.sender`) *into the data payload* to preserve provenance.
   * Calls `somniaStreams.esstores(...)` using its *own* contract address.
3. **Somnia Data Streams:** Records the data. To the Streams contract, the **only publisher** is your DApp Contract's address.

The Result:

Your global leaderboard aggregator now only needs to make one single read call to fetch all 10,000 players' data:

`sdk.streams.getAllPublisherDataForSchema(schemaId, YOUR_DAPP_CONTRACT_ADDRESS)`

This is massively scalable and efficient for read-heavy applications.

## Tutorial: Building a `GameLeaderboard` Proxy

Let's build a conceptual example of this pattern.

## What You'll Build

1. **A new Schema** that *includes* the original publisher's address.
2. **A `GameLeaderboard.sol`** smart contract that acts as the proxy.
3. **A Client Script** that writes to the *proxy contract* instead of Streams.
4. **A new Aggregator** that reads from the *proxy contract's* address.

## The Schema (Solving for Provenance)

Since the `msg.sender` to the Streams contract will always be our *proxy contract*, we lose the built-in provenance. We must re-create it by adding the original player's address to the schema itself.

**`src/lib/schema.ts`**

```typescript
// Schema: 'uint64 timestamp, address player, uint256 score'
export const leaderboardSchema = 
  'uint64 timestamp, address player, uint256 score'

```

## The Proxy Smart Contract (Solidity)

This is a new smart contract you would write and deploy for your DApp. It acts as the gatekeeper.

**SDK set() vs. Contract esstores()**\
This example uses the low-level contract function esstores().\
When you use sdk.streams.set() in your client-side code, the SDK is calling the esstores() function on the Somnia Streams contract "under the hood."\
This proxy contract is simply calling that same function directly.

**`src/contracts/GameLeaderboard.sol`**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// A simplified interface for the Somnia Streams contract
interface IStreams {
    struct DataStream {
        bytes32 id;
        bytes32 schemaId;
        bytes data;
    }
    // This is the correct low-level function name
    function esstores(DataStream[] calldata streams) external;
}

/**
 * @title GameLeaderboard
 * This contract is a DApp Publisher Proxy.
 * Users call submitScore() here.
 * This contract then calls somniaStreams.esstores() as a single publisher.
 */
contract GameLeaderboard {
    IStreams public immutable somniaStreams;
    bytes32 public immutable leaderboardSchemaId;

    event ScoreSubmitted(address indexed player, uint256 score);

    /**
     * @param _streamsAddress The deployed address of the Somnia Streams contract 
     * (e.g., 0x6AB397FF662e42312c003175DCD76EfF69D048Fc on Somnia Testnet).
     * @param _schemaId The pre-computed schemaId for 'uint64 timestamp, address player, uint256 score'.
     */
    constructor(address _streamsAddress, bytes32 _schemaId) {
        somniaStreams = IStreams(_streamsAddress);
        leaderboardSchemaId = _schemaId;
    }

    /**
     * @notice Players call this function to submit their score.
     * @param score The player's score.
     */
    function submitScore(uint256 score) external {
        // 1. Get the original publisher's address
        address player = msg.sender;
        uint64 timestamp = uint64(block.timestamp);

        // 2. Encode the data payload to match the schema
        // Schema: 'uint64 timestamp, address player, uint256 score'
        bytes memory data = abi.encode(timestamp, player, score);

        // 3. Create a unique dataId (e.g., hash of player and time)
        bytes32 dataId = keccak256(abi.encodePacked(player, timestamp));

        // 4. Prepare the DataStream struct
        IStreams.DataStream[] memory d = new IStreams.DataStream[](1);
        d[0] = IStreams.DataStream({
            id: dataId,
            schemaId: leaderboardSchemaId,
            data: data
        });

        // 5. Call Somnia Streams. The `msg.sender` for this call
        // is THIS contract (GameLeaderboard).
        somniaStreams.esstores(d);

        // 6. Emit a DApp-specific event for good measure
        emit ScoreSubmitted(player, score);
    }
}

```

## The Client Script (Publishing to the Proxy)

The client-side logic changes. The user no longer needs the Streams SDK to publish, but rather a way to call your DApp's `submitScore` function.

**`src/scripts/publishScore.ts`**

```typescript
import 'dotenv/config'
import { createWalletClient, http, createPublicClient, parseAbi } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { somniaTestnet } from '../lib/chain' // From previous tutorials
import { waitForTransactionReceipt } from 'viem/actions'

// --- DApp Contract Setup ---
// This is the address you get after deploying GameLeaderboard.sol
const DAPP_CONTRACT_ADDRESS = '0x...' // Your deployed GameLeaderboard contract address

// A minimal ABI for our GameLeaderboard contract
const DAPP_ABI = parseAbi([
  'function submitScore(uint256 score) external',
])
// --- --- ---

function getEnv(key: string): string {
  const value = process.env[key]
  if (!value) throw new Error(`Missing environment variable: ${key}`)
  return value
}

// We can use any publisher wallet
const walletClient = createWalletClient({
  account: privateKeyToAccount(getEnv('PUBLISHER_1_PK') as `0x${string}`),
  chain: somniaTestnet,
  transport: http(getEnv('RPC_URL')),
})

const publicClient = createPublicClient({
  chain: somniaTestnet,
  transport: http(getEnv('RPC_URL')),
})

async function main() {
  const newScore = Math.floor(Math.random() * 10000)
  console.log(`Player ${walletClient.account.address} submitting score: ${newScore}...`)

  try {
    const { request } = await publicClient.simulateContract({
      account: walletClient.account,
      address: DAPP_CONTRACT_ADDRESS,
      abi: DAPP_ABI,
      functionName: 'submitScore',
      args: [BigInt(newScore)],
    })

    const txHash = await walletClient.writeContract(request)
    console.log(`Transaction sent, hash: ${txHash}`)

    await waitForTransactionReceipt(publicClient, { hash: txHash })
    console.log('Score submitted successfully!')

  } catch (e: any) {
    console.error(`Failed to submit score: ${e.message}`)
  }
}

main().catch(console.error)

```

## The Aggregator Script (Simple, Scalable Reads)

This is the pay-off. The aggregator script is now *dramatically* simpler and more scalable. It only needs to know the single DApp contract address.

**`src/scripts/readLeaderboard.ts`**

```typescript
import 'dotenv/config'
import { SDK, SchemaDecodedItem } from '@somnia-chain/streams'
import { createPublicClient, http } from 'viem'
import { somniaTestnet } from '../lib/chain'
import { leaderboardSchema } from '../libL/schema' // Our new schema

// --- DApp Contract Setup ---
const DAPP_CONTRACT_ADDRESS = '0x...' // Your deployed GameLeaderboard contract address
// --- --- ---

function getEnv(key: string): string {
  const value = process.env[key]
  if (!value) throw new Error(`Missing environment variable: ${key}`)
  return value
}

const publicClient = createPublicClient({
  chain: somniaTestnet,
  transport: http(getEnv('RPC_URL')),
})

// Helper to decode the leaderboard data
interface ScoreRecord {
  timestamp: number
  player: `0x${string}`
  score: bigint
}

function decodeScoreRecord(row: SchemaDecodedItem[]): ScoreRecord {
  const val = (field: any) => field?.value?.value ?? field?.value ?? ''
  return {
    timestamp: Number(val(row[0])),
    player: val(row[1]) as `0x${string}`,
    score: BigInt(val(row[2])),
  }
}

async function main() {
  // The aggregator only needs a public client
  const sdk = new SDK({ public: publicClient })
  
  const schemaId = await sdk.streams.computeSchemaId(leaderboardSchema)
  if (!schemaId) throw new Error('Could not compute schemaId')

  console.log('--- Global Leaderboard Aggregator ---')
  console.log(`Reading all data from proxy: ${DAPP_CONTRACT_ADDRESS}\n`)

  // 1. Make ONE call to get all data for the DApp
  const data = await sdk.streams.getAllPublisherDataForSchema(
    schemaId,
    DAPP_CONTRACT_ADDRESS
  )

  if (!data || data.length === 0) {
    console.log('No scores found.')
    return
  }

  // 2. Decode and sort the records
  const allScores = (data as SchemaDecodedItem[][]).map(decodeScoreRecord)
  allScores.sort((a, b) => (b.score > a.score ? 1 : -1)) // Sort descending by score

  // 3. Display the leaderboard
  console.log(`Total scores found: ${allScores.length}\n`)
  allScores.forEach((record, index) => {
    console.log(
      `#${index + 1}: Player ${record.player} - Score: ${record.score} (at ${new Date(record.timestamp).toISOString()})`
    )
  })
}

main().catch(console.error)

```

## Trade-Offs & Considerations

This pattern is powerful, but it's important to understand the trade-offs.

| **Feature**            | **Standard Pattern (Multi-Publisher)**                | **Proxy Pattern (Single Publisher)**                                               |
| ---------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------- |
| **Read Scalability**   | **Low.** Requires N read calls (N = # of publishers). | **High.** Requires 1 read call, regardless of publisher count.                     |
| **Publisher Gas Cost** | **Low.** 1 transaction (`streams.set`).               | **High.** 1 transaction + 1 internal transaction. User pays more gas.              |
| **Provenance**         | **Automatic & Implicit.** `msg.sender` is the user.   | **Manual.** Must be built into the schema (`address player`).                      |
| **Complexity**         | **Simple.** Requires only the SDK.                    | **Complex.** Requires writing, deploying, and maintaining a custom smart contract. |

#### Conclusion

The **DApp Publisher Proxy** is an advanced but essential pattern for any Somnia Data Streams application that needs to scale to thousands or millions of publishers (e.t., games, social media, large IoT networks).

It simplifies the data aggregation logic from **`N+1`** read calls down to **`1`**, at the cost of higher gas fees for publishers and increased development complexity.

For most DApps, we recommend starting with the simpler "Multi-Publisher Aggregator" pattern. When your application's read performance becomes a bottleneck due to a high number of publishers, you can evolve to this proxy pattern to achieve massive read scalability.


# Build a Minimal On-Chain Chat App

In this Tutorial, you’ll build a tiny chat app where messages are published on-chain using the Somnia Data Streams SDK and then read back using a Subscriber pattern (fixed schema ID and publisher). The User Interface updates with simple polling and does not rely on  WebSocket.

We will build a Next.js project using app router and Typescript, and create a simple chat schema for messages. Using Somnia Data Streams, we will create a publisher API that writes to the Somnia chain and create a Subscriber API that reads from the Somnia chain by `schemaId` and publisher. The User Interface will poll new messages every few seconds.

## Prerequisites

* Node.js 20+
* A funded Somnia Testnet wallet. Kindly get some from the [Faucet](https://testnet.somnia.network/)
* Basic familiarity with TypeScript and Next.js

## Project Setup

Create the app by creating a directory where the app will live

```bash
npx create-next-app@latest somnia-chat --ts --app --no-tailwind
cd somnia-chat
```

Install the [Somnia Streams](https://www.npmjs.com/package/@somnia-chain/streams) and ViemJS dependencies

```bash
npm i @somnia-chain/streams viem
```

Somnia Data Streams is a Typescript SDK with methods that power off-chain reactivity. The application requires the ViemJS `provider` and `wallet` methods to enable queries over `https` embedded in the Somnia Data Streams SDK.

`viem` is a web3 library for the JS/TS ecosystem that simplifies reading and writing data from the Somnia chain. Importantly, it detaches wallets (and sensitive info) from the SDS SDK\
Set up the TypeScript environment by running the command:

```bash
npm i -D @types/node
```

Next.js provides a simple, full-stack environment.

## Configure environment variables

Create `.env.local` file. &#x20;

```markup
RPC_URL=https://dream-rpc.somnia.network
PRIVATE_KEY=0xYOUR_FUNDED_PRIVATE_KEY
CHAT_PUBLISHER=0xYOUR_WALLET_ADDRESS
```

The `RPC_URL` establishes the connection to Somnia Testnet, and the `PRIVATE_KEY` is used to sign and publish transactions. Note that it is kept server-side only. `CHAT_PUBLISHER` define what the Subscriber reads.

Never expose PRIVATE\_KEY to the browser. Keep all publishing code in API routes or server code only.\
\
NOTE: You can connect a Privy Wallet (or equivalent) to the SDK, avoiding the need entirely for private keys

## Chain Configuration

Create a `lib` folder and define the Somnia Testnet chain. This tells `viem` which chain we’re on, so clients know the RPC and formatting rules. `src/lib/chain.ts`

```typescript
import { defineChain } from 'viem'
export const somniaTestnet = defineChain({
  id: 50312,
  name: 'Somnia Testnet',
  network: 'somnia-testnet',
  nativeCurrency: { name: 'STT', symbol: 'STT', decimals: 18 },
  rpcUrls: {
    default: { http: ['https://dream-rpc.somnia.network'], 
               webSocket: ['wss://dream-rpc.somnia.network/ws'] },
    public:  { http: ['https://dream-rpc.somnia.network'],
               webSocket: ['wss://dream-rpc.somnia.network/ws'] },
  },
} as const)
```

## SDK Clients

Create public and wallet clients. Public client read-only RPC calls, and the Wallet client publishes transactions signed with your server wallet. We intentionally don’t set up WebSocket clients since we’re using polling for the User Interface. Create a file `clients` `src/lib/clients.ts`

```typescript
import { createPublicClient, createWalletClient, http } from 'viem'
import { privateKeyToAccount, type PrivateKeyAccount } from 'viem/accounts'
import { somniaTestnet } from './chain'

export function getPublicHttpClient() {
  return createPublicClient({
    chain: somniaTestnet,
    transport: http(RPC_URL),
  })
}

export function getWalletClient() {
  return createWalletClient({
    account: privateKeyToAccount(need('PRIVATE_KEY') as `0x${string}`),
    chain: somniaTestnet,
    transport: http(RPC_URL),
  })
}

export const publisherAddress = () => getAccount().address
```

## Schema

Chat schema is the structure of each message. This ordered list of typed fields defines how messages are encoded/decoded on-chain. Create a file `chatSchema` `src/lib/chatSchema.ts`

```typescript
export const chatSchema = 'uint64 timestamp, bytes32 roomId, string content, string senderName, address sender'
```

## Chat Service

We’ll build `chatService.ts` in small pieces so it’s easy to follow.

### Imports and helpers

```typescript
import { SDK, SchemaEncoder, zeroBytes32 } from '@somnia-chain/streams'
import { getPublicHttpClient, getWalletClient, publisherAddress } from './clients'
import { waitForTransactionReceipt } from 'viem/actions'
import { toHex, type Hex } from 'viem'
import { chatSchema } from './chatSchema'

const encoder = new SchemaEncoder(chatSchema)

const sdk = new SDK({
  public: getPublicHttpClient(),
  wallet: getWalletClient(),
})
```

`SchemaEncoder` handles encoding/decoding for the exact schema string.

`getSdk(true)` attaches the wallet client for publishing; read-only otherwise.

`assertHex` ensures transaction hashes are hex strings.

### Ensure the schema is registered

```typescript
// Register schema
  const schemaId = await sdk.streams.computeSchemaId(chatSchema)
  const isRegistered = await sdk.streams.isDataSchemaRegistered(schemaId)
  if (!isRegistered) {
    const ignoreAlreadyRegistered = true
    const txHash = await sdk.streams.registerDataSchemas(
      [{ schemaName: 'chat', schema: chatSchema, parentSchemaId: zeroBytes32 }],
      ignoreAlreadyRegistered
    )
    if (!txHash) throw new Error('Failed to register schema')
    await waitForTransactionReceipt(getPublicHttpClient(), { hash: txHash })
  }
```

If this schema wasn’t registered yet, we register it once. It’s safe to call this before sending the first message.

### Publish a message

```typescript
const now = Date.now().toString()
  const roomId = toHex(room, { size: 32 })
  const data: Hex = encoder.encodeData([
    { name: 'timestamp', value: now, type: 'uint64' },
    { name: 'roomId', value: roomId, type: 'bytes32' },
    { name: 'content', value: content, type: 'string' },
    { name: 'senderName', value: senderName, type: 'string' },
    { name: 'sender', value: getWalletClient().account.address, type: 'address' },
  ])

  const dataId = toHex(`${room}-${now}`, { size: 32 })
  const tx = await sdk.streams.set([{ id: dataId, schemaId, data }])
  if (!tx) throw new Error('Failed to publish chat message')
  await waitForTransactionReceipt(getPublicHttpClient(), { hash: tx })
  return { txHash: tx }
```

* We encode fields in the exact order specified in the schema.
* `setAndEmitEvents` writes the encoded payload.

The `sendMessage` function publishes a structured chat message to **Somnia Data Streams** while simultaneously emitting an event that can be captured in real time by subscribers. It creates a schema encoder for the chat message structure, encodes the message data, and prepares event topics for the `ChatMessage` event. Then, with a single `setAndEmitEvents()` transaction, it both stores the message and emits an event on-chain. Once the transaction is confirmed, the function returns the transaction hash, confirming the message was successfully written to the network. Complete code below:

<details>

<summary>chatService.ts</summary>

```typescript
// src/lib/chatService.ts
import { SDK, SchemaEncoder, zeroBytes32 } from '@somnia-chain/streams'
import { getPublicHttpClient, getWalletClient } from './clients'
import { waitForTransactionReceipt } from 'viem/actions'
import { toHex, type Hex } from 'viem'
import { chatSchema } from './chatSchema'

const encoder = new SchemaEncoder(chatSchema)

export async function sendMessage(room: string, content: string, senderName: string) {
  const sdk = new SDK({
    public: getPublicHttpClient(),
    wallet: getWalletClient(),
  })

  // Compute or register schema
  const schemaId = await sdk.streams.computeSchemaId(chatSchema)
  const isRegistered = await sdk.streams.isDataSchemaRegistered(schemaId)
  if (!isRegistered) {
    const ignoreAlreadyRegistered = true
    const txHash = await sdk.streams.registerDataSchemas(
      [{ id: 'chat', schema: chatSchema, parentSchemaId: zeroBytes32 }],
      ignoreAlreadyRegistered
    )
    if (!txHash) throw new Error('Failed to register schema')
    await waitForTransactionReceipt(getPublicHttpClient(), { hash: txHash })
  }

  const now = Date.now().toString()
  const roomId = toHex(room, { size: 32 })
  const data: Hex = encoder.encodeData([
    { name: 'timestamp', value: now, type: 'uint64' },
    { name: 'roomId', value: roomId, type: 'bytes32' },
    { name: 'content', value: content, type: 'string' },
    { name: 'senderName', value: senderName, type: 'string' },
    { name: 'sender', value: getWalletClient().account.address, type: 'address' },
  ])

  const dataId = toHex(`${room}-${now}`, { size: 32 })
  const tx = await sdk.streams.set([{ id: dataId, schemaId, data }])
  if (!tx) throw new Error('Failed to publish chat message')
  await waitForTransactionReceipt(getPublicHttpClient(), { hash: tx })
  return { txHash: tx }
}

```

</details>

### Read Messages

Create a `chatMessages.ts` file to write the script for reading messages.

* `getAllPublisherDataForSchema` reads all publisher data for your (schemaId, publisher).

The `fetchChatMessages` function connects to the **Somnia Data Streams SDK** using a public client and derives the schema ID from the local chat schema. It then retrieves all data entries published by the specified wallet for that schema, decodes them into readable message objects, and filters them by room if a name is provided. Each message is timestamped, ordered chronologically, and limited to a given count before being returned. The result is a clean, decoded list of on-chain messages. Complete code below:

<details>

<summary>chatMessages.ts</summary>

```typescript
'use client'
import { useEffect, useState, useCallback, useRef } from 'react'
import { SDK } from '@somnia-chain/streams'
import { getPublicHttpClient } from './clients'
import { chatSchema } from './chatSchema'
import { toHex, type Hex } from 'viem'

// Helper to unwrap field values
const val = (f: any) => f?.value?.value ?? f?.value

// Message type
export type ChatMsg = {
  timestamp: number
  roomId: `0x${string}`
  content: string
  senderName: string
  sender: `0x${string}`
}

/**
 * Fetch chat messages from Somnia Streams (read-only, auto-refresh, cumulative)
 */
export function useChatMessages(
  roomName?: string,
  limit = 100,
  refreshMs = 5000
) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<NodeJS.Timeout | null>(null)

  const loadMessages = useCallback(async () => {
    try {
      const sdk = new SDK({ public: getPublicHttpClient() })

      // Compute schema ID from the chat schema
      const schemaId = await sdk.streams.computeSchemaId(chatSchema)
      const publisher =
        process.env.NEXT_PUBLIC_PUBLISHER_ADDRESS ??
        '0x0000000000000000000000000000000000000000'

      // Fetch all publisher data for schema
      const resp = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisher)

      // Ensure array structure (each row corresponds to an array of fields)
      const rows: any[][] = Array.isArray(resp) ? (resp as any[][]) : []
      if (!rows.length) {
        setMessages([])
        setLoading(false)
        return
      }

      // Convert room name to bytes32 for filtering (if applicable)
      const want = roomName ? toHex(roomName, { size: 32 }).toLowerCase() : null

      const parsed: ChatMsg[] = []
      for (const row of rows) {
        if (!Array.isArray(row) || row.length < 5) continue

        const ts = Number(val(row[0]))
        const ms = String(ts).length <= 10 ? ts * 1000 : ts // handle seconds vs ms
        const rid = String(val(row[1])) as `0x${string}`

        // Skip messages from other rooms if filtered
        if (want && rid.toLowerCase() !== want) continue

        parsed.push({
          timestamp: ms,
          roomId: rid,
          content: String(val(row[2]) ?? ''),
          senderName: String(val(row[3]) ?? ''),
          sender: (String(val(row[4])) as `0x${string}`) ??
            '0x0000000000000000000000000000000000000000',
        })
      }

      // Sort by timestamp (ascending)
      parsed.sort((a, b) => a.timestamp - b.timestamp)

      // Deduplicate and limit
      setMessages((prev) => {
        const combined = [...prev, ...parsed]
        const unique = combined.filter(
          (msg, index, self) =>
            index ===
            self.findIndex(
              (m) =>
                m.timestamp === msg.timestamp &&
                m.sender === msg.sender &&
                m.content === msg.content
            )
        )
        return unique.slice(-limit)
      })

      setError(null)
    } catch (err: any) {
      console.error('❌ Failed to load chat messages:', err)
      setError(err.message || 'Failed to load messages')
    } finally {
      setLoading(false)
    }
  }, [roomName, limit])

  // Initial load + polling
  useEffect(() => {
    setLoading(true)
    loadMessages()
    timerRef.current = setInterval(loadMessages, refreshMs)
    return () => timerRef.current && clearInterval(timerRef.current)
  }, [loadMessages, refreshMs])

  return { messages, loading, error, reload: loadMessages }
}

```

</details>

## API Routes

To parse the data to the NextJS UI, we will create API route files that will enable us to call `sendMessage` and  `fetchChatMessages` functions

### Write Messages Endpoint&#x20;

`src/app/api/send/route.ts`

```typescript
import { NextResponse } from 'next/server'
import { sendMessage } from '@/lib/chatService'

export async function POST(req: Request) {
  try {
    const { room, content, senderName } = await req.json()
    if (!room || !content) throw new Error('Missing fields')
    const { txHash } = await sendMessage(room, content, senderName)
    return NextResponse.json({ success: true, txHash })
  } catch (e: any) {
    console.error(e)
    return NextResponse.json({ error: e.message || 'Failed to send' }, { status: 500 })
  }
}
```

Publishes messages with the server wallet. We validate the input and return the tx hash.

## Frontend&#x20;

Update `src/app/page.tsx`  Connect the Somnia Data Streams logic to a simple frontend. Fetch messages stored on-chain, display them in real time, and send new ones.

#### Component Setup

```tsx
use client'
import { useState } from 'react'
import { useChatMessages } from '@/lib/chatMessages'

export default function Page() {
  const [room, setRoom] = useState('general')
  const [content, setContent] = useState('')
  const [senderName, setSenderName] = useState('Victory')
  const [error, setError] = useState<string | null>(null)

  const {
    messages,
    loading,
    error: fetchError,
    reload,
  } = useChatMessages(room, 200)

  // --- Send new message via API route ---
  async function send() {
    try {
      if (!content.trim()) {
        setError('Message content cannot be empty')
        return
      }

      const res = await fetch('/api/send', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ room, content, senderName }),
      })

      const data = await res.json()
      if (!res.ok) throw new Error(data?.error || 'Failed to send message')

      setContent('')
      setError(null)
      reload() // refresh after sending
    } catch (e: any) {
      console.error('❌ Send message failed:', e)
      setError(e?.message || 'Failed to send message')
    }
  }
```

* `room`, `content`, and `senderName` store user input.
* `useChatMessages(room, 200)` reads the latest 200 messages from Somnia Data Streams using a **read-only SDK instance**.\
  The hook automatically polls for new messages every few seconds.
* The `send()` function publishes a new message by calling the `/api/send` endpoint, which writes on-chain using `sdk.streams.setAndEmitEvents()`.\
  After a message is successfully sent, the input clears and `reload()` is called to refresh the messages list.

The hook handles loading and error states internally, while the component keeps a separate `error` state for send failures.

#### UI Rendering

```tsx
  return (
    <main style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1>💬 Somnia Streams Chat (read-only)</h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={room}
          onChange={(e) => setRoom(e.target.value)}
          placeholder="room"
        />
        <input
          value={senderName}
          onChange={(e) => setSenderName(e.target.value)}
          placeholder="name"
        />
        <button onClick={reload} disabled={loading}>
          Refresh
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          style={{ flex: 1 }}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Type a message"
        />
        <button onClick={send}>Send</button>
      </div>

      {(error || fetchError) && (
        <div style={{ color: 'crimson', marginBottom: 12 }}>
          Error: {error || fetchError}
        </div>
      )}

      {loading ? (
        <p>Loading messages...</p>
      ) : !messages.length ? (
        <p>No messages yet.</p>
      ) : (
        <ul style={{ paddingLeft: 16 }}>
          {messages.map((m, i) => (
            <li key={i}>
              <small>{new Date(m.timestamp).toLocaleTimeString()} </small>
              <b>{m.senderName || m.sender}</b>: {m.content}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
```

* The top input fields let users change the chat room or display name, and manually refresh messages if needed.
* The second input and **Send** button allow posting new messages.
* Error messages appear in red if either sending or fetching fails.
* Below, the app dynamically renders one of three states:
  * “Loading messages…” while fetching.
  * “No messages yet.” if the room is empty.
  * A chat list showing messages with timestamps, names, and content.

Each message represents **on-chain data** fetched via Somnia Data Streams, fully verified, timestamped, and appended as part of the schema structure. We clear the input and trigger a delayed refresh so the message appears soon after mining.&#x20;

#### How It Works

This component bridges the Somnia SDK’s on-chain capabilities with React’s reactive rendering model.\
Whenever the user sends a message, the SDK publishes it to Somnia Data Streams via the backend `/api/send` route.\
Meanwhile, `useChatMessages` polls the blockchain for updates, decoding structured data stored by the same schema.\
As a result, each message displayed in the chat window is **a verifiable blockchain record**, yet the experience feels as fluid and fast as a typical Web2 chat.

```markup
+-----------+       +--------------------+      +---------------------+
|  User UI  | --->  |  Next.js API /send | ---> | Somnia Data Streams |
+-----------+       +--------------------+      +---------------------+
      ^                       |                           |
      |                       v                           |
      |             +------------------+                  |
      |             |   Blockchain     |                  |
      |             |  (Transaction)   |                  |
      |             +------------------+                  |
      |                       |                           |
      |<----------------------|                           |
      |     Poll via SDK or Subscribe (useChatMessages)   |
      +---------------------------------------------------+

```

Complete code below:

<details>

<summary>page.tsx</summary>

```typescript
'use client'
import { useState } from 'react'
import { useChatMessages } from '@/lib/chatMessages'

export default function Page() {
  const [room, setRoom] = useState('general')
  const [content, setContent] = useState('')
  const [senderName, setSenderName] = useState('Victory')
  const [error, setError] = useState<string | null>(null)

  const {
    messages,
    loading,
    error: fetchError,
    reload,
  } = useChatMessages(room, 200)

  // --- Send new message via API route ---
  async function send() {
    try {
      if (!content.trim()) {
        setError('Message content cannot be empty')
        return
      }

      const res = await fetch('/api/send', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ room, content, senderName }),
      })

      const data = await res.json()
      if (!res.ok) throw new Error(data?.error || 'Failed to send message')

      setContent('')
      setError(null)
      reload() // refresh after sending
    } catch (e: any) {
      console.error('❌ Send message failed:', e)
      setError(e?.message || 'Failed to send message')
    }
  }

  // --- Render UI ---
  return (
    <main
      style={{
        padding: 24,
        fontFamily: 'system-ui, sans-serif',
        maxWidth: 640,
        margin: '0 auto',
      }}
    >
      <h1>💬 Somnia Data Streams Chat</h1>
      <p style={{ color: '#666' }}>
        Messages are stored <b>onchain</b> and read using Somnia Data Streams.
      </p>

      {/* Room + Name inputs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={room}
          onChange={(e) => setRoom(e.target.value)}
          placeholder="room name"
          style={{ flex: 1, padding: 6 }}
        />
        <input
          value={senderName}
          onChange={(e) => setSenderName(e.target.value)}
          placeholder="your name"
          style={{ flex: 1, padding: 6 }}
        />
        <button
          onClick={reload}
          disabled={loading}
          style={{
            background: '#0070f3',
            color: 'white',
            border: 'none',
            padding: '6px 12px',
            cursor: 'pointer',
            borderRadius: 4,
          }}
        >
          Refresh
        </button>
      </div>

      {/* Message input */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          style={{ flex: 1, padding: 6 }}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Type your message..."
        />
        <button
          onClick={send}
          style={{
            background: '#28a745',
            color: 'white',
            border: 'none',
            padding: '6px 12px',
            cursor: 'pointer',
            borderRadius: 4,
          }}
        >
          Send
        </button>
      </div>

      {/* Error messages */}
      {(error || fetchError) && (
        <div style={{ color: 'crimson', marginBottom: 12 }}>
          Error: {error || fetchError}
        </div>
      )}

      {/* Message list */}
      {loading ? (
        <p>Loading messages...</p>
      ) : !messages.length ? (
        <p>No messages yet.</p>
      ) : (
        <ul style={{ paddingLeft: 16, listStyle: 'none' }}>
          {messages.map((m, i) => (
            <li key={i} style={{ marginBottom: 8 }}>
              <small style={{ color: '#666' }}>
                {new Date(m.timestamp).toLocaleTimeString()}
              </small>{' '}
              <b>{m.senderName || m.sender}</b>: {m.content}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

```

</details>

## Run the App

Run the program using the command:

```bash
npm run dev
```

Your app will be LIVE at <http://localhost:3000> in your browser

Tip

Open two browser windows to simulate two users watching the same room. Both will see new messages as the poller fetches fresh data.<br>

## Codebase

<https://github.com/emmaodia/somnia-streams-chat-demo>&#x20;

# Build a Realtime On-Chain Game

This tutorial shows how to build a Tap-to-Play Onchain Game using Somnia Data Streams, where every player’s tap is written directly to the blockchain and the leaderboard updates in realtime.

Each tap is stored onchain as a structured data record following a schema.\
The game uses MetaMask for wallet identity and Somnia Streams SDK to:

* Store tap events onchain using `sdk.streams.set()`
* Retrieve and rank all players from onchain data

By the end of this guide, you’ll have:\
\- A working Next.js app\
\- Onchain data storage using Somnia Data Streams\
\- A live leaderboard that reads blockchain state\
\- MetaMask integration for identity and transaction signing

***

## Prerequisites

* Node.js 20+
* A funded Somnia Testnet wallet. Kindly get some from the [Faucet](https://testnet.somnia.network/)
* Basic familiarity with TypeScript and Next.js

***

## Project Setup

Initialize a new Next.js app and install dependencies. Create the app by creating a directory where the app will live

```bash
npx create-next-app@latest somnia-chat --ts --app --no-tailwind
cd somnia-chat
```

Install the [Somnia Streams](https://www.npmjs.com/package/@somnia-chain/streams) and ViemJS dependencies

```bash
npm i @somnia-chain/streams viem
```

Create a .env.local file for storing secrets and environmental variables

```bash
NEXT_PUBLIC_PUBLISHER_ADDRESS=0xb6e4fa6ff2873480590c68D9Aa991e5BB14Dbf03
NEXT_PUBLIC_RPC_URL=https://dream-rpc.somnia.network
```

Never expose PRIVATE\_KEY to the browser. Keep all publishing code in API routes or server code only. NOTE: You can connect a Privy Wallet (or equivalent) to the SDK, avoiding the need entirely for private keys.

***

## Define Tap Schema <a href="#chain-configuration" id="chain-configuration"></a>

Create a file `lib/schema.ts`:

```typescript
// lib/schema.ts
export const tapSchema = 'uint64 timestamp, address player'
```

This schema defines the structure of each tap event:

* `timestamp`: when the tap occurred
* `player`: who tapped (wallet address)
* A `nonce` will be added when the schema is deployed to ensures each record is unique

The Schema ID will be automatically computed by the SDK from this schema.

***

## Setup Clients

Create `lib/serverClient.ts` for server-side reads:

```typescript
// lib/serverClient.ts
import { createPublicClient, http } from 'viem'
import { somniaTestnet } from 'viem/chains'

export function getServerPublicClient() {
  return createPublicClient({
    chain: somniaTestnet,
    transport: http(process.env.RPC_URL || 'https://dream-rpc.somnia.network'),
  })
}
```

Create `lib/clients.ts` for client-side access:

```typescript
// lib/clients.ts
'use client'
import { createPublicClient, http } from 'viem'
import { somniaTestnet } from 'viem/chains'

export function getPublicHttpClient() {
  return createPublicClient({
    chain: somniaTestnet,
    transport: http(process.env.NEXT_PUBLIC_RPC_URL || 'https://dream-rpc.somnia.network'),
  })
}
```

***

## Writing Tap Data Onchain

Each tap is recorded onchain with the `sdk.streams.set()` method. In this section, we’ll walk through how each part of the `sendTap()` logic works from wallet connection to writing structured schema data onchain.

***

### **Set up state variables**

We’ll start by tracking a number of states, such as:

* the connected wallet address
* the wallet client (MetaMask connection)
* and a few helper states for loading, cooldowns, and errors.

```tsx
const [address, setAddress] = useState('')
const [walletClient, setWalletClient] = useState<any>(null)
const [cooldownMs, setCooldownMs] = useState(0)
const [pending, setPending] = useState(false)
const [error, setError] = useState('')
```

These ensure that you can access the connected wallet address (`address`) and track transaction state (`pending`). It also prevents spam taps with a 1-second cooldown (`cooldownMs`)

***

### **Connect MetaMask**

We use the browser’s `window.ethereum` API to connect to MetaMask.\
Once connected, we create a **wallet client** that Somnia’s SDK can use for signing transactions.

```tsx
async function connectWallet() {
  if (typeof window !== "undefined" && window.ethereum !== undefined)
    try {
      await window.ethereum.request({ method: "eth_requestAccounts" });
      const walletClient = createWalletClient({
          chain: somniaDream,
          transport: custom(window.ethereum),
      });
      const [account] = await walletClient.getAddresses();
      setWalletClient(walletClient)
      setAddress(account)
    } catch (e: any) {
      setError(e?.message || String(e))
    }  setWalletClient(wallet)
}
```

`createWalletClient` from Viem wraps MetaMask into a signer object that the Somnia SDK can use.\
This is how the UI and the blockchain are bridged securely.

***

### **Initialize the SDK**

The **Somnia Data Streams SDK** provides methods to compute schema IDs, encode structured data, and publish to the blockchain. We initialize it with both the **public client** (for chain access) and the **wallet client** (for signing transactions).

```tsx
const sdk = new SDK({
  public: getPublicHttpClient(),
  wallet: walletClient,
})
```

This gives you full read/write access to the Somnia Streams contract on Somnia Testnet.

***

### **Compute the Schema ID**

Schemas define how the onchain data is structured. In this case, the tap schema looks like this:

```ts
tapSchema = 'uint64 timestamp, address player'
```

Before writing data, we must compute its **unique Schema ID**:

```tsx
const schemaId = await sdk.streams.computeSchemaId(tapSchema)
```

This produces a deterministic ID derived from the schema text, ensuring that any app using the same schema can read or decode your data.

***

### **Register the Schema**

```typescript
// Register schema
  const schemaId = await sdk.streams.computeSchemaId(chatSchema)
  const isRegistered = await sdk.streams.isDataSchemaRegistered(schemaId)
  if (!isRegistered) {
    const ignoreAlreadyRegistered = true
    const txHash = await sdk.streams.registerDataSchemas(
      [{ schemaName: 'tap', schema: tapSchema, parentSchemaId: zeroBytes32 }],
      ignoreAlreadyRegistered
    )
    if (!txHash) throw new Error('Failed to register schema')
    await waitForTransactionReceipt(getPublicHttpClient(), { hash: txHash })
  }
```

If this schema wasn’t registered yet, we register it once. It’s safe to call this before sending the first message.

### **Encode the Data**

Somnia Streams stores structured data using its `SchemaEncoder` class. We create an encoder and provide each field according to the schema definition.

```tsx
const encoder = new SchemaEncoder(tapSchema)
const now = BigInt(Date.now())

const data = encoder.encodeData([
  { name: 'timestamp', value: now, type: 'uint64' },
  { name: 'player', value: address, type: 'address' },
])
```

This converts your JavaScript values into the precise binary format that can be stored onchain and later decoded.

***

### **Generate a Unique Data ID**

Each record needs a **unique identifier** within the schema. We use the `keccak256` hash of the player’s address and timestamp to ensure that it is packed into 32 bits of data.

```tsx
const id = keccak256(toHex(`${address}-${Number(nonce)}`))
```

This ensures no two taps collide, even if the same player taps rapidly.

***

### **Store the Tap Onchain**

Finally, we push the structured data to the blockchain using:

```tsx
await sdk.streams.set([{ id, schemaId, data }])
```

The `set()` method writes one or more records (called *Data Streams*) to the chain.\
Each record is cryptographically signed by the player’s wallet, and gets stored on Somnia’s decentralized data infrastructure. It can also be retrieved instantly using the same schema

***

### **Manage Cooldowns and Feedback**

After the tap is sent, we apply a 1-second cooldown to avoid flooding transactions and reset the pending state.

```tsx
setCooldownMs(1000)
setPending(false)
```

This gives players a smooth UX while maintaining blockchain transaction integrity.

***

#### Putting It All Together

Here’s the complete `sendTap()` method with all steps combined:

```tsx
async function sendTap() {
  if (!walletClient || !address) return
  setPending(true)

  const sdk = new SDK({ public: getPublicHttpClient(), wallet: walletClient })
  const schemaId = await sdk.streams.computeSchemaId(tapSchema)
  const encoder = new SchemaEncoder(tapSchema)
  const now = BigInt(Date.now())

  const data = encoder.encodeData([
    { name: 'timestamp', value: now, type: 'uint64' },
    { name: 'player', value: address, type: 'address' },
  ])

  const id = keccak256(toHex(`${address}-${Number(now)}`))
  await sdk.streams.set([{ id, schemaId, data }])
  setCooldownMs(1000)
  setPending(false)
}
```

### Complete \`page.tsx\` Code

<details>

<summary>page.tsx</summary>

```typescript
'use client'
import { useState, useEffect, useRef } from 'react'
import { SDK, SchemaEncoder } from '@somnia-chain/streams'
import { getPublicHttpClient } from '@/lib/clients'
import { tapSchema } from '@/lib/schema'
import { keccak256, toHex, createWalletClient, custom } from 'viem'
import { somniaTestnet } from 'viem/chains'

export default function Page() {
  const [address, setAddress] = useState('')
  const [walletClient, setWalletClient] = useState<any>(null)
  const [leaderboard, setLeaderboard] = useState<{ address: string; count: number }[]>([])
  const [cooldownMs, setCooldownMs] = useState(0)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const lastNonce = useRef<number>(0)

  async function connectWallet() {
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
    const wallet = createWalletClient({
      chain: somniaTestnet,
      transport: custom(window.ethereum),
    })
    setAddress(accounts[0])
    setWalletClient(wallet)
  }
  async function sendTap() {
    if (!walletClient || !address) return
    setPending(true)
    const sdk = new SDK({ public: getPublicHttpClient(), wallet: walletClient })
    const schemaId = await sdk.streams.computeSchemaId(tapSchema)
    const encoder = new SchemaEncoder(tapSchema)
    const now = BigInt(Date.now())
    const data = encoder.encodeData([
      { name: 'timestamp', value: now, type: 'uint64' },
      { name: 'player', value: address, type: 'address' },
      { name: 'nonce', value: BigInt(lastNonce.current++), type: 'uint256' },
    ])
    const id = keccak256(toHex(`${address}-${Number(now)}`))
    await sdk.streams.set([{ id, schemaId, data }])
    setCooldownMs(1000)
    setPending(false)
  }

  return (
    <main style={{ padding: 24 }}>
      <h1>🚀 Somnia Tap Game</h1>
      {!address ? (
        <button onClick={connectWallet}>🦊 Connect MetaMask</button>
      ) : (
        <p>Connected: {address.slice(0, 6)}...{address.slice(-4)}</p>
      )}
      <button onClick={sendTap} disabled={pending || cooldownMs > 0 || !address}>
        {pending ? 'Sending...' : '🖱️ Tap'}
      </button>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <Leaderboard leaderboard={leaderboard} />
    </main>
  )
}

function Leaderboard({ leaderboard }: { leaderboard: { address: string; count: number }[] }) {
  if (!leaderboard.length) return <p>No taps yet</p>
  return (
    <ol>
      {leaderboard.map((p, i) => (
        <li key={p.address}>
          #{i + 1} {p.address} — {p.count} taps
        </li>
      ))}
    </ol>
  )
}
```

</details>

***

## Reading Leaderboard Data Onchain

The leaderboard is calculated server-side by reading all tap data stored onchain. Create a `lib/store.ts` file and add the following code:

```typescript
lib/store.ts
import { SDK } from '@somnia-chain/streams'
import { getServerPublicClient } from './serverClient'
import { tapSchema } from './schema'

const publisher =
  process.env.NEXT_PUBLIC_PUBLISHER_ADDRESS ||
  '0x0000000000000000000000000000000000000000'
const val = (f: any) => f?.value?.value ?? f?.value

export async function getLeaderboard() {
  const sdk = new SDK({ public: getServerPublicClient() })
  const schemaId = await sdk.streams.computeSchemaId(tapSchema)
  const rows = await sdk.streams.getAllPublisherDataForSchema(schemaId, publisher)
  if (!Array.isArray(rows)) return []

  const counts = new Map<string, number>()
  for (const row of rows) {
    const player = String(val(row[1]) ?? '').toLowerCase()
    if (!player.startsWith('0x')) continue
    counts.set(player, (counts.get(player) || 0) + 1)
  }

  return Array.from(counts.entries())
    .map(([address, count]) => ({ address, count }))
    .sort((a, b) => b.count - a.count)
}
```

The leaderboard logic begins inside the `getLeaderboard()` function, where we use the **SDK** to read structured tap data directly from the blockchain. First, the function initializes the SDK with a **server-compatible public client**, which allows read-only access to the chain without a connected wallet. The next step computes the `schemaId` by passing our `tapSchema` to `sdk.streams.computeSchemaId()`. This produces a deterministic identifier that ensures we’re always referencing the correct data structure.

Once the `schemaId` is known, the core operation happens through `sdk.streams.getAllPublisherDataForSchema(schemaId, publisher)`. This method queries the blockchain for all records written by the specified publisher under that schema. Each returned record is an array of fields that align with the schema’s definition, in this case `[timestamp, player]`. The helper function `val()` is then used to unwrap nested field values (`f?.value?.value`) from the SDK’s response format, giving us clean, readable values.

`getAllPublisherDataForSchema` acts like a decentralized “SELECT \* FROM” query, fetching all onchain data tied to a schema and publisher, while the rest of the function transforms that raw blockchain data into a structured leaderboard the app can display.<br>

***

Creat a api route to retrieve Leaderboard score. Create the file `app/api/leaderboard/route.ts`

```typescript
import { NextResponse } from 'next/server'
import { getLeaderboard } from '@/lib/store'

export async function GET() {
  const leaderboard = await getLeaderboard()
  return NextResponse.json({ leaderboard })
}
```

This endpoint imports the `getLeaderboard()` function from `lib/store.ts`, which handles the heavy lifting of querying Somnia Data Streams, and then exposes that onchain data as a clean, JSON-formatted response for your application. The client simply fetches the leaderboard via `/api/leaderboard`. <br>

The page.tsx fetches /api/leaderboard every few seconds to stay updated.

***

Every tap executes a real blockchain transaction:

| Field     | Description                  |
| --------- | ---------------------------- |
| timestamp | Time of the tap              |
| player    | Wallet address of the player |

When the `set()` call succeeds, Somnia Data Streams stores the record and indexes it under your publisher’s address. Any application (including yours) can then read this data and build dashboards, analytics, or game leaderboards.

***

## Run the App

```bash
npm run dev
```

Open[ http://localhost:3000](http://localhost:3000) and connect your MetaMask wallet. Click 🖱️ Tap to send onchain transactions, and watch your leaderboard update live.

***

## Conclusion

You’ve built a fully onchain game where player interactions are stored via Somnia Data Streams and leaderboard rankings are derived from immutable blockchain data. MetaMask provides secure, user-friendly authentication. This same pattern powers realtime Web3 experiences, from social apps to competitive games, using Somnia’s high-performance onchain data infrastructure.
