# BTC_Balance_checker
Python script to check bulk addresses for balances from your own Bitcoin node
Simply change the Rpc login details for your RPC access in the python file.
You need to be running your own full node or have RPC access to one
Pruned nodes will not work correctly

This is a really fastest way to check bulk lists!

Uses GPU to validate addresses (AMD only) Will fall back to CPU if not possible or error detected.

Ensure bitcoin.conf has:

rpcuser=your_rpc_username
rpcpassword=your_rpc_password
rpcbind=127.0.0.1
rpcport=8332
rpcworkqueue=32
rpcthreads=8

Also pip install pyopencl python-bitcoinrpc bitcoinaddress pandas numpy base58

Ensure you have an address list file. Test one included.


To do
speed up further optimise.

bitcoin tips accepted here
16w9ywEv1bkyGyfriZYSj5msrkxc2e9CLD
