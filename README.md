# BTC_Balance_checker FAST
Python script to check bulk addresses for balances from your own Bitcoin node.
Simply change the Rpc login details for your RPC access in the python file.
You need to be running your own full node or have RPC access to one.
Pruned nodes will not work correctly!

This is a really fast way to check bulk lists without paying for 3rd party api calls!

Uses GPU to validate addresses (AMD only) Will fall back to CPU if not possible or error detected.

Ensure bitcoin.conf has:

rpcuser=your_rpc_username

rpcpassword=your_rpc_password

rpcallowip=127.0.0.1

rpcbind=127.0.0.1

rpcport=8332

rpcworkqueue=256     # Increased for heavy scantxoutset load

rpcthreads=128       # More threads for RPC handling

rpctimeout=300       # Increased timeout for slow operations

prune=0              # Must be non-pruned

dbcache=8192         # 8GB cache (adjust to 4096 if <16GB RAM)

maxmempool=2000      # Larger mempool

server=1

txindex=1            # Optional, speeds up lookups (requires reindex)

Also pip install pyopencl python-bitcoinrpc bitcoinaddress pandas numpy base58

Ensure you have an address list file. Test one included.

Batch size is set to 1000 but you can change to whatever your system can handle.

To do
speed up and further optimise.

bitcoin tips accepted here!

16w9ywEv1bkyGyfriZYSj5msrkxc2e9CLD

To run make sure your node is fully synced add your own address list called bitcoin_addresses.txt in the same directory you run the python sript from.


example output after running>
Results saved to bitcoin_balances.csv

Summary of Results
--------------------------------------------------
Total Addresses Processed: 1992
Addresses with Non-Zero Balance: 1
Addresses with Balances:
  1DDWbJhKqfidczaHF1ugGP2KzPgcaU3tGD: 5869.40013427 BTC
Total Balance Found: 5869.40013427 BTC
--------------------------------------------------
