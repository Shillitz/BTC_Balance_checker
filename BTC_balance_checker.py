from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from bitcoinaddress import Address
import time
import pandas as pd

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

# Function to connect to Bitcoin Core RPC
def connect_to_rpc():
    try:
        # Replace with your RPC credentials and host/port
        rpc_user = "your_rpc_username"
        rpc_password = "your_rpc_password"
        rpc_host = "127.0.0.1"
        rpc_port = 8332
        rpc_url = f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}"
        return AuthServiceProxy(rpc_url)
    except Exception as e:
        print(f"Error connecting to Bitcoin RPC: {e}")
        return None

# Function to convert address to legacy (P2PKH) format
def convert_to_legacy(address, rpc_connection):
    try:
        # Validate address using RPC
        validation = rpc_connection.validateaddress(address)
        if not validation['isvalid']:
            return None, "Invalid address", "Unknown"
        
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
def check_balance(rpc_connection, address, addr_type):
    try:
        # Validate address first
        validation = rpc_connection.validateaddress(address)
        if not validation['isvalid']:
            return None, "Invalid address"
        
        # Try importing address (for legacy wallets, only P2PKH should be passed)
        try:
            rpc_connection.importaddress(address, "", False)
        except JSONRPCException as e:
            if "Only legacy wallets are supported" in str(e):
                print(f"Legacy wallet error for {address}: {e}. Attempting balance check without import.")
                try:
                    utxos = rpc_connection.listunspent(0, 9999999, [address])
                    balance_satoshis = sum(utxo['amount'] * 100_000_000 for utxo in utxos)
                    return balance_satoshis / 100_000_000, None
                except JSONRPCException as e2:
                    return None, f"Fallback failed: {e2}"
            else:
                return None, f"RPC error: {e}"
        
        # Get unspent transaction outputs (UTXOs)
        utxos = rpc_connection.listunspent(0, 9999999, [address])
        balance_satoshis = sum(utxo['amount'] * 100_000_000 for utxo in utxos)
        return balance_satoshis / 100_000_000, None
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
        print("Failed to connect to Bitcoin
