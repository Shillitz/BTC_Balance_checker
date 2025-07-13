# BTC_Balance_checker
Python script to check bulk addresses for balances from your own Bitcoin node
Simply change the Rpc login details for your RPC access.
You need to be running your own node or have RPC access to one

How to UseVerify Bitcoin Node:Ensure bitcoind is running and synced:bash

bitcoin-cli getblockchaininfo

Check verificationprogress ~1.0.
Confirm wallet type:bash

bitcoin-cli getwalletinfo

The script is compatible with legacy wallets (default in older Bitcoin Core versions).

Install Libraries:bash

pip install python-bitcoinrpc bitcoinaddress pandas

Prepare Text File:
Create bitcoin_addresses.txt with addresses, e.g.:

1KJtNFDsvTYrJKh5zAwAGPpjY168W5vHfr
3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy
bc1qar0srrr7xfkxy5l643lydnw9re59gtzzwf5mdq

Update RPC Credentials:
In connect_to_rpc, replace rpc_user, rpc_password, rpc_host, and rpc_port with your bitcoin.conf credentials.
Run the Script:
Save as convert_btc_addresses.py and run:bash

python convert_btc_addresses.py

Expected Output:
The script will print detailed results for each address, followed by a summary highlighting non-zero balances. Example:
```
Converting addresses to legacy format and checking balances...Original Address: 1KJtNFDsvTYrJKh5zAwAGPpjY168W5vHfr
Address Type: P2PKH
Legacy Address: 1KJtNFDsvTYrJKh5zAwAGPpjY168W5vHfr
Balance: 0.00000000 BTC
Conversion Status: Already legacyOriginal Address: 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy
Address Type: P2SH
Legacy Address: 1HsKGL1eTsimqRWnM7N4zKCaW1TKL3JRYd
Balance: 0.00000000 BTC
Conversion Status: Converted from P2SHOriginal Address: bc1qar0srrr7xfkxy5l643lydnw9re59gtzzwf5mdq
Address Type: P2WPKH
Legacy Address: 1C4rXz7aN1v6KkM4vTq1jV4C3zq8gS4z8
Balance: 0.01234567 BTC
Conversion Status: Converted from Bech32Results saved to bitcoin_balances.csvSummary of ResultsTotal Addresses Processed: 3
Addresses with Non-Zero Balance: 1
Addresses with Balances:
  bc1qar0srrr7xfkxy5l643lydnw9re59gtzzwf5mdq: 0.01234567 BTC
Total Balance Found: 0.01234567 BTC

The CSV (`bitcoin_balances.csv`) will contain:

Original Address,Legacy Address,Balance (BTC),Balance Error,Address Type,Conversion Status
1KJtNFDsvTYrJKh5zAwAGPpjY168W5vHfr,1KJtNFDsvTYrJKh5zAwAGPpjY168W5vHfr,0.00000000,,P2PKH,Already legacy
3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy,1HsKGL1eTsimqRWnM7N4zKCaW1TKL3JRYd,0.00000000,,P2SH,Converted from P2SH
bc1qar0srrr7xfkxy5l643lydnw9re59gtzzwf5mdq,1C4rXz7aN1v6KkM4vTq1jV4C3zq8gS4z8,0.01234567,,P2WPKH,Converted from Bech32
,,,,,
Summary,,,,
Total Addresses Processed,3,,,,
Addresses with Non-Zero Balance,1,,,,
Total Balance (BTC),0.01234567,,,,
Non-Zero Balance: bc1qar0srrr7xfkxy5l643lydnw9re59gtzzwf5mdq,0.01234567,,,,

NotesSummary Details:Total Addresses Processed: Counts all addresses in the input file.
Addresses with Non-Zero Balance: Counts addresses where balance is not None and greater than 0.
Addresses with Balances: Lists each address with a non-zero balance and its value.
Total Balance Found: Sums all valid balances (including zero balances).

CSV Format:The summary is appended to the CSV with blank rows for readability.
Non-zero balance addresses are listed individually in the summary section.

Performance:The summary adds minimal overhead, as it processes already-collected data.
The 0.1s delay between RPC calls ensures the node isn’t overloaded.

Error Handling:The script retains robust error handling for invalid addresses, RPC errors, and legacy wallet limitations.
The summary only includes valid balances (where balance is not None).

