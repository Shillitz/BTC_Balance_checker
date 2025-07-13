from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from bitcoinaddress import Address
import time
import pandas as pd
import http.client
import socket

# Function to read Bitcoin addresses from a text file
def read_addresses(file_path):
    try:
        with open(file_path, 'r') as file:
            addresses = [line.strip() for line in file if line.strip()]
        return addresses
    except FileNotFoundError:
        print(f"Error: File {file_path} not found.")
        return []
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

# Function to connect to Bitcoin Core RPC with retry
def connect_to_rpc(max_retries=3, retry_delay=5):
    for attempt in range(max_retries):
        try:
            # Replace with your RPC credentials and host/port
            rpc_user = "changehere"
            rpc_password = "changehere"
            rpc_host = "127.0.0.1"
            rpc_port = 8332
            rpc_url = f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}"
            # Timeout set to 120 seconds for large UTXO scans
            return AuthServiceProxy(rpc_url, timeout=120)
        except Exception as e:
            print(f"Error connecting to Bitcoin RPC (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    return None

# Function to check if node is pruned
def check_pruned_node(rpc_connection):
    try:
        blockchain_info = rpc_connection.getblockchaininfo()
        if blockchain_info.get('pruned', False):
            print("WARNING: Node is pruned, which prevents accurate balance reporting for historical addresses (e.g., genesis block address 1HLoD9E4SDFFPDiYfNYnkBLQ85Y51J3Zb1).")
            print("To fix, set 'prune=0' in bitcoin.conf, delete blockchain data (keep wallet.dat), and resync the node.")
            print("Resyncing a non-pruned node may take hours/days depending on hardware.")
            return True
        return False
    except Exception as e:
        print(f"Error checking pruned status: {e}")
        return False

# Function to convert address to legacy (P2PKH) format
def convert_to_legacy(address, rpc_connection):
    addr_type = "Unknown"  # Initialize to avoid UnboundLocalError
    try:
        # Validate address using RPC with retry
        for attempt in range(3):
            try:
                validation = rpc_connection.validateaddress(address)
                break
            except (JSONRPCException, http.client.HTTPException, socket.timeout) as e:
                print(f"validateaddress error for {address} (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(5)
                else:
                    return None, f"Validation error: {e}", addr_type
        
        if not validation['isvalid']:
            return None, "Invalid address", addr_type
        
        # Determine address type from scriptPubKey
        scriptpubkey = validation.get('scriptPubKey', '')
        addr_type = "P2PKH" if scriptpubkey.startswith('76a914') else \
                    "P2SH" if scriptpubkey.startswith('a914') else \
                    "P2WPKH" if scriptpubkey.startswith('0014') else \
                    "P2WSH" if scriptpubkey.startswith('0020') else "Unknown"
        
        # For P2PKH, return the address as-is
        if addr_type == "P2PKH":
            return address, "Already legacy", addr_type
        
        # Parse non-P2PKH addresses using bitcoinaddress library
        try:
            addr_obj = Address(address)
        except Exception as e:
            return None, f"Address parsing error: {e}", addr_type
        
        # Convert P2SH-P2WPKH to legacy
        if addr_type == "P2SH" and hasattr(addr_obj.mainnet, 'pubaddr_p2sh_p2wpkh') and addr_obj.mainnet.pubaddr_p2sh_p2wpkh:
            hash160 = scriptpubkey[4:-2]  # Remove 'a914' prefix and '87' suffix
            legacy_addr = Address.from_hash160(hash160, 'mainnet', 'pubkeyhash')
            return legacy_addr.mainnet.pubaddr, "Converted from P2SH", addr_type
        
        # Convert P2WPKH (Bech32) to legacy
        if addr_type == "P2WPKH" and hasattr(addr_obj.mainnet, 'pubaddr_bech32') and addr_obj.mainnet.pubaddr_bech32:
            hash160 = scriptpubkey[4:]  # Remove '0014' prefix
            legacy_addr = Address.from_hash160(hash160, 'mainnet', 'pubkeyhash')
            return legacy_addr.mainnet.pubaddr, "Converted from Bech32", addr_type
        
        return None, "Cannot convert complex or unsupported address type", addr_type
    except Exception as e:
        return None, f"Conversion error: {e}", addr_type

# Function to check balance for a single Bitcoin address
def check_balance(rpc_connection, address):
    try:
        # Validate address first
        validation = rpc_connection.validateaddress(address)
        if not validation['isvalid']:
            return None, "Invalid address"
        
        # Special handling for genesis address
        if address == "1HLoD9E4SDFFPDiYfNYnkBLQ85Y51J3Zb1":
            total_balance = 0.0
            balance_error = None
            try:
                # Check genesis block coinbase transaction
                genesis_txid = "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
                genesis_block = rpc_connection.getblockhash(0)
                tx = rpc_connection.getrawtransaction(genesis_txid, 1, genesis_block)
                for vout in tx['vout']:
                    if vout['scriptPubKey'].get('addresses', [None])[0] == address:
                        total_balance += vout['value']
                        print(f"Found genesis UTXO: {vout['value']:.8f} BTC (txid: {genesis_txid}, vout: {vout['n']})")
                # Also check other UTXOs with scantxoutset
                result = rpc_connection.scantxoutset("start", [{"desc": f"addr({address})"}])
                if result['success']:
                    utxos = result.get('unspents', [])
                    total_balance += result['total_amount']
                    print(f"Found {len(utxos)} additional UTXOs for {address}, total: {result['total_amount']} BTC")
                    if utxos:
                        print("Additional UTXO details:", [{"txid": utxo['txid'], "vout": utxo['vout'], "amount": f"{utxo['amount']:.8f} BTC"} for utxo in utxos])
                    else:
                        print("No additional UTXOs found.")
                    rpc_connection.scantxoutset("abort", [])  # Clean up
                    if total_balance == result['total_amount']:
                        print("Warning: Genesis UTXO (50 BTC) not included in scantxoutset, likely due to Bitcoin Core excluding unspendable UTXOs.")
                    return total_balance, None
                else:
                    print("scantxoutset failed to find additional UTXOs, relying on genesis transaction.")
                    return total_balance, None
            except (JSONRPCException, http.client.HTTPException, socket.timeout) as e:
                print(f"Genesis transaction check error for {address}: {e}")
                balance_error = f"Genesis check failed: {e}"
        
        # Use scantxoutset for other addresses
        for attempt in range(3):
            try:
                result = rpc_connection.scantxoutset("start", [{"desc": f"addr({address})"}])
                if result['success']:
                    utxos = result.get('unspents', [])
                    balance_satoshis = int(result['total_amount'] * 100_000_000)
                    print(f"Found {len(utxos)} UTXOs for {address}, total: {result['total_amount']} BTC")
                    if utxos:
                        print("UTXO details:", [{"txid": utxo['txid'], "vout": utxo['vout'], "amount": f"{utxo['amount']:.8f} BTC"} for utxo in utxos])
                    else:
                        print("No UTXOs found.")
                    rpc_connection.scantxoutset("abort", [])  # Clean up
                    return balance_satoshis / 100_000_000, None
                else:
                    return None, "scantxoutset failed to find UTXOs"
            except (JSONRPCException, http.client.HTTPException, socket.timeout) as e:
                print(f"scantxoutset error for {address} (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(5)
                else:
                    return None, f"scantxoutset failed: {e}"
    except JSONRPCException as e:
        return None, f"RPC error: {e}"
    except Exception as e:
        return None, f"Error checking balance: {e}"

# Function to save results to CSV with summary
def save_results(addresses, legacy_addresses, balances, errors, addr_types, statuses):
    # Detailed results DataFrame
    df = pd.DataFrame({
        'Original Address': addresses,
        'Legacy Address': [addr if addr else "N/A" for addr in legacy_addresses],
        'Balance (BTC)': [f"{b:.8f}" if b is not None else "N/A" for b in balances],
        'Balance Error': [e if e else "" for e in errors],
        'Address Type': addr_types,
        'Conversion Status': statuses
    })
    
    # Summary data
    total_addresses = len(addresses)
    non_zero_balances = [(addr, bal) for addr, bal in zip(addresses, balances) if bal is not None and bal > 0]
    num_non_zero = len(non_zero_balances)
    total_balance = sum(bal for bal in balances if bal is not None)
    
    # Append summary to CSV
    summary_data = [
        ["", "", "", "", "", ""],
        ["Summary", "", "", "", "", ""],
        [f"Total Addresses Processed", total_addresses, "", "", "", ""],
        [f"Addresses with Non-Zero Balance", num_non_zero, "", "", "", ""],
        [f"Total Balance (BTC)", f"{total_balance:.8f}", "", "", "", ""]
    ]
    for addr, bal in non_zero_balances:
        summary_data.append([f"Non-Zero Balance: {addr}", f"{bal:.8f}", "", "", "", ""])
    
    summary_df = pd.DataFrame(summary_data, columns=df.columns)
    final_df = pd.concat([df, summary_df], ignore_index=True)
    final_df.to_csv('bitcoin_balances.csv', index=False)
    print("Results saved to bitcoin_balances.csv")
    
    # Print summary to console
    print("\nSummary of Results")
    print("-" * 50)
    print(f"Total Addresses Processed: {total_addresses}")
    print(f"Addresses with Non-Zero Balance: {num_non_zero}")
    if num_non_zero > 0:
        print("Addresses with Balances:")
        for addr, bal in non_zero_balances:
            print(f"  {addr}: {bal:.8f} BTC")
    else:
        print("No addresses with non-zero balances found.")
    print(f"Total Balance Found: {total_balance:.8f} BTC")
    print("-" * 50)

# Main function to process addresses, convert to legacy, and check balances
def main():
    file_path = 'bitcoin_addresses.txt'  # Replace with your text file path
    addresses = read_addresses(file_path)
    
    if not addresses:
        print("No valid addresses found in the file.")
        return
    
    # Connect to Bitcoin RPC
    rpc_connection = connect_to_rpc()
    if not rpc_connection:
        print("Failed to connect to Bitcoin node. Exiting.")
        return
    
    # Check if node is pruned
    check_pruned_node(rpc_connection)
    
    print("Converting addresses to legacy format and checking balances...")
    print("-" * 50)
    
    legacy_addresses = []
    balances = []
    balance_errors = []
    statuses = []
    addr_types = []
    
    for address in addresses:
        # Convert to legacy format
        legacy_address, status, addr_type = convert_to_legacy(address, rpc_connection)
        legacy_addresses.append(legacy_address)
        statuses.append(status)
        addr_types.append(addr_type)
        
        # Check balance using legacy address if available, otherwise skip
        balance = None
        balance_error = None
        if legacy_address:
            balance, balance_error = check_balance(rpc_connection, legacy_address)
        else:
            balance_error = "Skipped due to conversion failure"
            print(f"Skipping balance check for {address} due to conversion failure")
        
        balances.append(balance)
        balance_errors.append(balance_error)
        
        print(f"Original Address: {address}")
        print(f"Address Type: {addr_type}")
        print(f"Legacy Address: {legacy_address if legacy_address else 'N/A'}")
        print(f"Balance: {balance:.8f} BTC" if balance is not None else f"Balance: Unable to retrieve ({balance_error})")
        print(f"Conversion Status: {status}")
        print("-" * 50)
        time.sleep(0.2)  # Increased delay to avoid overloading node
    
    # Save results and print summary
    save_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses)

if __name__ == "__main__":
    main()
