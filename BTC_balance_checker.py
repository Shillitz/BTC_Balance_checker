from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import time
import pandas as pd
import http.client
import socket
import json
from decimal import Decimal
import logging

try:
    from bitcoinlib.keys import Address
except ImportError:
    Address = None
    print("Warning: bitcoinlib not installed. Address conversion limited to P2PKH.")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    filename="balance_checker.log",
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def read_addresses(file_path):
    try:
        with open(file_path, 'r') as file:
            addresses = [line.strip() for line in file if line.strip()]
            if not addresses:
                logging.error(f"{file_path} is empty or contains no valid addresses.")
                print(f"Error: {file_path} is empty or contains no valid addresses.")
                return []
            logging.info(f"Read {len(addresses)} addresses from {file_path}")
            return addresses
    except FileNotFoundError:
        logging.error(f"File {file_path} not found.")
        print(f"Error: File {file_path} not found.")
        return []
    except Exception as e:
        logging.error(f"Error reading file: {e}")
        print(f"Error reading file: {e}")
        return []

def convert_to_legacy(address, rpc_connection):
    addr_type = "Unknown"
    try:
        for attempt in range(7):
            try:
                validation = rpc_connection.validateaddress(address)
                break
            except (JSONRPCException, http.client.HTTPException, socket.timeout, ConnectionResetError, ConnectionAbortedError) as e:
                logging.warning(f"validateaddress error for {address} (attempt {attempt + 1}/7): {e}")
                print(f"validateaddress error for {address} (attempt {attempt + 1}/7): {e}")
                if attempt < 6:
                    time.sleep(5)
                else:
                    return None, f"Validation error: {e}", addr_type, None
        
        if not validation['isvalid']:
            return None, "Invalid address", addr_type, None
        
        scriptpubkey = validation.get('scriptPubKey', '')
        addr_type = "P2PKH" if scriptpubkey.startswith('76a914') else \
                    "P2SH" if scriptpubkey.startswith('a914') else \
                    "P2WPKH" if scriptpubkey.startswith('0014') else \
                    "P2WSH" if scriptpubkey.startswith('0020') else "Unknown"
        
        if addr_type == "P2PKH":
            return address, "Already legacy", addr_type, scriptpubkey
        
        if Address is None:
            return None, "Cannot convert: bitcoinlib not installed", addr_type, None
        
        try:
            addr_obj = Address(address)
        except Exception as e:
            return None, f"Address parsing error: {e}", addr_type, None
        
        if addr_type == "P2SH" and hasattr(addr_obj, 'script_type') and addr_obj.script_type == 'p2sh_p2wpkh':
            hash160 = scriptpubkey[4:-2]
            legacy_addr = Address(hash160=hash160, network='bitcoin', script_type='p2pkh')
            return legacy_addr.address, "Converted from P2SH", addr_type, f"76a914{hash160}88ac"
        
        if addr_type == "P2WPKH":
            hash160 = scriptpubkey[4:]
            legacy_addr = Address(hash160=hash160, network='bitcoin', script_type='p2pkh')
            return legacy_addr.address, "Converted from Bech32", addr_type, f"76a914{hash160}88ac"
        
        return None, "Cannot convert complex or unsupported address type", addr_type, None
    except Exception as e:
        logging.error(f"Conversion error for {address}: {e}")
        return None, f"Conversion error: {e}", addr_type, None

def connect_to_rpc(max_retries=7, retry_delay=5):
    for attempt in range(max_retries):
        try:
            rpc_user = "yourdetails"
            rpc_password = "yourpass"
            rpc_host = "127.0.0.1"
            rpc_port = 8332
            rpc_url = f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}"
            rpc_connection = AuthServiceProxy(rpc_url, timeout=300)
            rpc_connection.getblockchaininfo()
            logging.info("Successfully connected to Bitcoin RPC")
            return rpc_connection
        except Exception as e:
            logging.warning(f"Error connecting to Bitcoin RPC (attempt {attempt + 1}/{max_retries}): {e}")
            print(f"Error connecting to Bitcoin RPC (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    logging.error("Failed to connect to Bitcoin node after maximum retries")
    return None

def check_pruned_node(rpc_connection):
    try:
        blockchain_info = rpc_connection.getblockchaininfo()
        if blockchain_info.get('pruned', False):
            logging.error("Node is pruned, balance checks may be inaccurate")
            print("ERROR: Node is pruned, balance checks may be inaccurate. Please resync with prune=0.")
            return True
        logging.info("Node is not pruned")
        return False
    except Exception as e:
        logging.error(f"Error checking pruned status: {e}")
        print(f"Error checking pruned status: {e}")
        return False

def ensure_scantxoutset_ready(rpc_connection, max_retries=10, retry_delay=10):
    for attempt in range(max_retries):
        try:
            status = rpc_connection.scantxoutset("status", [])
            if status and status.get('progress') is not None:
                logging.warning(f"scantxoutset in progress (progress: {status['progress']:.2f}%). Aborting...")
                print(f"scantxoutset in progress (progress: {status['progress']:.2f}%). Aborting...")
                rpc_connection.scantxoutset("abort", [])
                time.sleep(2)  # Wait for abort to complete
                # Verify abort was successful
                status = rpc_connection.scantxoutset("status", [])
                if status and status.get('progress') is not None:
                    logging.warning(f"scantxoutset still in progress after abort (progress: {status['progress']:.2f}%)")
                    print(f"scantxoutset still in progress after abort (progress: {status['progress']:.2f}%)")
                    time.sleep(retry_delay)
                    continue
            return True
        except (JSONRPCException, http.client.HTTPException, socket.timeout, ConnectionAbortedError, ConnectionResetError) as e:
            logging.warning(f"Error checking scantxoutset status (attempt {attempt + 1}/{max_retries}): {e}")
            print(f"Error checking scantxoutset status (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logging.error("Failed to ensure scantxoutset is ready after maximum retries")
                print("Failed to ensure scantxoutset is ready after maximum retries")
                return False
    return False

def check_balance_batch(rpc_connection, addresses):
    balances = {addr: 0.0 for addr in addresses}
    errors = {addr: None for addr in addresses}
    genesis_address = "1HLoD9E4SDFFPDiYfNYnkBLQ85Y51J3Zb1"

    try:
        if not ensure_scantxoutset_ready(rpc_connection):
            logging.error("Failed to ensure scantxoutset is ready")
            return balances, {addr: "Failed to ensure scantxoutset is ready" for addr in addresses}

        if genesis_address in addresses:
            balances[genesis_address] = 50.0
            logging.info(f"Added genesis UTXO for {genesis_address}: 50.00000000 BTC")
            print(f"Added genesis UTXO for {genesis_address}: 50.00000000 BTC (hardcoded due to Bitcoin Core limitation)")

        descriptors = [{"desc": f"addr({addr})", "range": 0} for addr in addresses]
        logging.info(f"Scanning {len(descriptors)} addresses with scantxoutset")

        for attempt in range(7):
            try:
                result = rpc_connection.scantxoutset("start", descriptors)
                if result['success']:
                    utxos = result.get('unspents', [])
                    addr_balances = {addr: 0.0 for addr in addresses}
                    for utxo in utxos:
                        addr = utxo['desc'].split('addr(')[1].split(')')[0]
                        if addr in addr_balances:
                            addr_balances[addr] += float(utxo['amount'])

                    for addr in addresses:
                        addr_balance = addr_balances.get(addr, 0.0)
                        if addr_balance > 0:
                            logging.info(f"Found UTXOs for {addr}, total: {addr_balance:.8f} BTC")
                            print(f"Found UTXOs for {addr}, total: {addr_balance:.8f} BTC")
                            utxos_for_addr = [u for u in utxos if u['desc'].split('addr(')[1].split(')')[0] == addr]
                            if utxos_for_addr:
                                utxos_for_json = [
                                    {k: float(v) if isinstance(v, Decimal) else v for k, v in u.items()}
                                    for u in utxos_for_addr[:3]
                                ]
                                logging.debug(f"First 3 UTXOs for {addr}: {json.dumps(utxos_for_json, indent=2)}")
                                print(f"Debug: First 3 UTXOs for {addr}: {json.dumps(utxos_for_json, indent=2)}")
                        balances[addr] = addr_balance
                        logging.debug(f"Total balance for {addr}: {balances[addr]:.8f} BTC")
                        print(f"Debug: Total balance for {addr} after adding: {balances[addr]:.8f} BTC")

                    rpc_connection.scantxoutset("abort", [])
                    return balances, errors
                else:
                    logging.error("scantxoutset failed for batch")
                    print(f"scantxoutset failed for batch")
                    return balances, {addr: "scantxoutset failed to find UTXOs" for addr in addresses}
            except (JSONRPCException, http.client.HTTPException, socket.timeout, ConnectionAbortedError, ConnectionResetError) as e:
                logging.warning(f"scantxoutset error (attempt {attempt + 1}/7): {e}")
                print(f"scantxoutset error for batch (attempt {attempt + 1}/7): {e}")
                if attempt < 6:
                    time.sleep(5)
                else:
                    logging.error(f"scantxoutset failed after retries: {e}")
                    return balances, {addr: f"scantxoutset failed: {e}" for addr in addresses}
    except Exception as e:
        logging.error(f"Error checking balance: {e}")
        return balances, {addr: f"Error checking balance: {e}" for addr in addresses}

def save_partial_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses, section_num):
    df = pd.DataFrame({
        'Original Address': addresses,
        'Legacy Address': [addr if addr else "N/A" for addr in legacy_addresses],
        'Balance (BTC)': [f"{bal:.8f}" if bal is not None else "N/A" for bal in balances],
        'Balance Error': [err if err else "" for err in balance_errors],
        'Address Type': addr_types,
        'Conversion Status': statuses
    })
    df.to_csv(f'bitcoin_balances_section_{section_num}.csv', index=False)
    logging.info(f"Saved partial results for section {section_num} to bitcoin_balances_section_{section_num}.csv")
    print(f"Saved partial results for section {section_num}")

def save_results(addresses, legacy_addresses, balances, errors, addr_types, statuses):
    logging.info("Saving final results to bitcoin_balances.csv")
    print(f"Debug: Lengths - addresses: {len(addresses)}, legacy_addresses: {len(legacy_addresses)}, balances: {len(balances)}, errors: {len(errors)}, addr_types: {len(addr_types)}, statuses: {len(statuses)}")
    df = pd.DataFrame({
        'Original Address': addresses,
        'Legacy Address': [addr if addr else "N/A" for addr in legacy_addresses],
        'Balance (BTC)': [f"{bal:.8f}" if bal is not None else "N/A" for bal in balances],
        'Balance Error': [err if err else "" for err in errors],
        'Address Type': addr_types,
        'Conversion Status': statuses
    })
    
    total_addresses = len(addresses)
    non_zero_balances = [(addr, bal) for addr, bal in zip(addresses, balances) if bal is not None and bal > 0]
    num_non_zero = len(non_zero_balances)
    total_balance = sum(bal for bal in balances if bal is not None)
    
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
    logging.info("Results saved to bitcoin_balances.csv")
    print("Results saved to bitcoin_balances.csv")
    
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

def main():
    file_path = 'bitcoin_addresses.txt'
    addresses = read_addresses(file_path)
    
    if not addresses:
        logging.error("No valid addresses found in the file. Exiting.")
        print("No valid addresses found in the file.")
        return
    
    # Initialize lists for results
    legacy_addresses = [None] * len(addresses)
    statuses = [None] * len(addresses)
    addr_types = [None] * len(addresses)
    balances = [0.0] * len(addresses)
    balance_errors = ["Skipped due to conversion failure"] * len(addresses)
    
    # Split addresses into sections of 1000
    section_size = 1000
    sections = [addresses[i:i + section_size] for i in range(0, len(addresses), section_size)]
    print(f"Split {len(addresses)} addresses into {len(sections)} sections of up to {section_size} addresses")
    logging.info(f"Split {len(addresses)} addresses into {len(sections)} sections of up to {section_size} addresses")
    
    for section_idx, section_addresses in enumerate(sections):
        print(f"\nProcessing section {section_idx + 1} of {len(sections)} with {len(section_addresses)} addresses...")
        logging.info(f"Processing section {section_idx + 1} of {len(sections)} with {len(section_addresses)} addresses")
        
        # Connect to Bitcoin RPC
        rpc_connection = connect_to_rpc()
        if not rpc_connection:
            logging.error(f"Failed to connect to Bitcoin node for section {section_idx + 1}. Skipping.")
            print(f"Failed to connect to Bitcoin node for section {section_idx + 1}. Skipping.")
            for j, addr in enumerate(section_addresses):
                global_idx = section_idx * section_size + j
                if global_idx < len(addresses):
                    balance_errors[global_idx] = "Failed to connect to Bitcoin node"
            save_partial_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses, section_idx + 1)
            continue
        
        # Check if node is pruned
        if check_pruned_node(rpc_connection):
            logging.error(f"Node is pruned. Exiting section {section_idx + 1}.")
            print(f"Node is pruned. Exiting section {section_idx + 1}.")
            for j, addr in enumerate(section_addresses):
                global_idx = section_idx * section_size + j
                if global_idx < len(addresses):
                    balance_errors[global_idx] = "Node is pruned"
            save_partial_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses, section_idx + 1)
            continue
        
        # Convert addresses to legacy format
        section_results = [convert_to_legacy(addr, rpc_connection) for addr in section_addresses]
        section_valid_addresses = []
        
        for j, (legacy_address, status, addr_type, scriptpubkey) in enumerate(section_results):
            global_idx = section_idx * section_size + j
            if global_idx >= len(addresses):
                break
            address = addresses[global_idx]
            legacy_addresses[global_idx] = legacy_address
            statuses[global_idx] = status
            addr_types[global_idx] = addr_type
            if legacy_address:
                section_valid_addresses.append(legacy_address)
            print(f"Original Address: {address}")
            print(f"Address Type: {addr_type}")
            print(f"Legacy Address: {legacy_address if legacy_address else 'N/A'}")
            print(f"Conversion Status: {status}")
            if scriptpubkey:
                print(f"ScriptPubKey: {scriptpubkey}")
            print("-" * 50)
            logging.info(f"Processed {address}: Type={addr_type}, Legacy={legacy_address or 'N/A'}, Status={status}")
            time.sleep(0.01)
        
        # Check balances for valid addresses in the section
        if section_valid_addresses:
            print(f"Checking balances for {len(section_valid_addresses)} valid addresses in section {section_idx + 1}...")
            logging.info(f"Checking balances for {len(section_valid_addresses)} valid addresses in section {section_idx + 1}")
            batch_balances, batch_errors = check_balance_batch(rpc_connection, section_valid_addresses)
            for j, addr in enumerate(section_addresses):
                global_idx = section_idx * section_size + j
                if global_idx >= len(addresses):
                    break
                if addr in section_valid_addresses or (addr in addresses and legacy_addresses[global_idx] in section_valid_addresses):
                    idx = section_valid_addresses.index(legacy_addresses[global_idx]) if legacy_addresses[global_idx] in section_valid_addresses else j
                    balances[global_idx] = batch_balances.get(section_valid_addresses[idx], 0.0)
                    balance_errors[global_idx] = batch_errors.get(section_valid_addresses[idx], None)
                    print(f"Debug: Assigned balance for {addr}: {balances[global_idx]:.8f} BTC, error: {balance_errors[global_idx]}")
                    logging.info(f"Assigned balance for {addr}: {balances[global_idx]:.8f} BTC, error: {balance_errors[global_idx]}")
                    print(f"Original Address: {addr}")
                    print(f"Balance: {balances[global_idx]:.8f} BTC" if balances[global_idx] is not None else f"Balance: Unable to retrieve ({balance_errors[global_idx]})")
                    print("-" * 50)
                    time.sleep(0.01)
        else:
            for j, addr in enumerate(section_addresses):
                global_idx = section_idx * section_size + j
                if global_idx >= len(addresses):
                    break
                print(f"Debug: Skipped balance check for {addr} due to conversion failure")
                logging.info(f"Skipped balance check for {addr} due to conversion failure")
                print(f"Original Address: {addr}")
                print(f"Balance: 0.00000000 BTC")
                print("-" * 50)
                time.sleep(0.01)
        
        # Save partial results
        save_partial_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses, section_idx + 1)
        
        # Delay before next section (no explicit disconnect)
        time.sleep(2)
        logging.info(f"Waiting 2 seconds before starting section {section_idx + 2}")
        print(f"Waiting 10 seconds before starting section {section_idx + 2}")
    
    # Save final results
    save_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses)

if __name__ == "__main__":
    main()
