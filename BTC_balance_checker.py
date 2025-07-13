from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import time
import pandas as pd
import http.client
import socket
import json
from decimal import Decimal
import pyopencl as cl
import numpy as np
import base58
import hashlib

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

# OpenCL kernel for address validation
OPENCL_KERNEL = """
__kernel void validate_address(__global const char *addresses,
                              __global int *address_lengths,
                              __global int *valid_flags,
                              const int max_addr_len)
{
    int gid = get_global_id(0);
    int addr_len = address_lengths[gid];
    if (addr_len < 25 || addr_len > 35) {
        valid_flags[gid] = 0;
        return;
    }

    // Check for valid Base58 characters
    int valid = 1;
    for (int i = 0; i < addr_len; i++) {
        char c = addresses[gid * max_addr_len + i];
        if (!((c >= '1' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'))) {
            valid = 0;
            break;
        }
    }
    valid_flags[gid] = valid;
}
"""

# Function to validate addresses using OpenCL
def opencl_validate_addresses(addresses, platform_id=0):
    try:
        # Initialize OpenCL
        platforms = cl.get_platforms()
        if not platforms or platform_id >= len(platforms):
            print(f"Error: No OpenCL platform found or invalid platform_id {platform_id}")
            return [(None, "OpenCL platform error", "Unknown", None) for _ in addresses]
        
        platform = platforms[platform_id]
        devices = platform.get_devices()
        if not devices:
            print("Error: No OpenCL devices found")
            return [(None, "OpenCL device error", "Unknown", None) for _ in addresses]
        
        device = next((d for d in devices if d.type == cl.device_type.GPU), devices[0])
        context = cl.Context([device])
        queue = cl.CommandQueue(context)
        program = cl.Program(context, OPENCL_KERNEL).build()

        # Prepare input data
        max_addr_len = max(len(addr) for addr in addresses) + 1
        addr_buffer = np.array([list(addr.ljust(max_addr_len, '\0').encode('ascii')) for addr in addresses], dtype=np.int8)
        addr_lengths = np.array([len(addr) for addr in addresses], dtype=np.int32)
        valid_flags = np.zeros(len(addresses), dtype=np.int32)

        # Create OpenCL buffers
        addr_buf = cl.Buffer(context, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=addr_buffer)
        len_buf = cl.Buffer(context, cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR, hostbuf=addr_lengths)
        valid_buf = cl.Buffer(context, cl.mem_flags.WRITE_ONLY, valid_flags.nbytes)

        # Execute kernel
        program.validate_address(queue, (len(addresses),), None, addr_buf, len_buf, valid_buf, np.int32(max_addr_len))
        queue.finish()

        # Read results
        cl.enqueue_copy(queue, valid_flags, valid_buf)

        results = []
        for i, addr in enumerate(addresses):
            if valid_flags[i]:
                # Perform Base58 decoding and checksum verification
                try:
                    decoded = base58.b58decode(addr)
                    if len(decoded) != 25 or decoded[0] != 0x00:  # Mainnet P2PKH
                        results.append((None, "Invalid address (format)", "Unknown", None))
                        continue
                    checksum = decoded[-4:]
                    hash160 = decoded[1:-4]
                    expected_checksum = hashlib.sha256(hashlib.sha256(decoded[:-4]).digest()).digest()[:4]
                    if checksum != expected_checksum:
                        results.append((None, "Invalid address (checksum)", "Unknown", None))
                        continue
                    scriptpubkey = f"76a914{hash160.hex()}88ac"
                    results.append((addr, "Already legacy", "P2PKH", scriptpubkey))
                except Exception:
                    results.append((None, "Invalid address (decoding)", "Unknown", None))
            else:
                results.append((None, "Invalid address (OpenCL)", "Unknown", None))
        
        return results
    except Exception as e:
        print(f"OpenCL error: {e}")
        return [(None, f"OpenCL error: {e}", "Unknown", None) for _ in addresses]

# CPU-based address validation and conversion
def convert_to_legacy(address, rpc_connection):
    addr_type = "Unknown"
    try:
        for attempt in range(3):
            try:
                validation = rpc_connection.validateaddress(address)
                break
            except (JSONRPCException, http.client.HTTPException, socket.timeout) as e:
                print(f"validateaddress error for {address} (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2)
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
        
        try:
            from bitcoinaddress import Address
            addr_obj = Address(address)
        except Exception as e:
            return None, f"Address parsing error: {e}", addr_type, None
        
        if addr_type == "P2SH" and hasattr(addr_obj.mainnet, 'pubaddr_p2sh_p2wpkh') and addr_obj.mainnet.pubaddr_p2sh_p2wpkh:
            hash160 = scriptpubkey[4:-2]
            legacy_addr = Address.from_hash160(hash160, 'mainnet', 'pubkeyhash')
            return legacy_addr.mainnet.pubaddr, "Converted from P2SH", addr_type, f"76a914{hash160}88ac"
        
        if addr_type == "P2WPKH" and hasattr(addr_obj.mainnet, 'pubaddr_bech32') and addr_obj.mainnet.pubaddr_bech32:
            hash160 = scriptpubkey[4:]
            legacy_addr = Address.from_hash160(hash160, 'mainnet', 'pubkeyhash')
            return legacy_addr.mainnet.pubaddr, "Converted from Bech32", addr_type, f"76a914{hash160}88ac"
        
        return None, "Cannot convert complex or unsupported address type", addr_type, None
    except Exception as e:
        return None, f"Conversion error: {e}", addr_type, None

# Function to connect to Bitcoin Core RPC with retry
def connect_to_rpc(max_retries=3, retry_delay=2):
    for attempt in range(max_retries):
        try:
            rpc_user = "your_rpc_username"
            rpc_password = "your_rpc_password"
            rpc_host = "127.0.0.1"
            rpc_port = 8332
            rpc_url = f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}"
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
            print("WARNING: Node is pruned, which may prevent accurate balance reporting for historical addresses.")
            print("To fix, set 'prune=0' in bitcoin.conf, delete blockchain data (keep wallet.dat), and resync the node.")
            return True
        return False
    except Exception as e:
        print(f"Error checking pruned status: {e}")
        return False

# Function to check balances for a batch of addresses
def check_balance_batch(rpc_connection, addresses):
    try:
        # Prepare batch descriptors
        descriptors = [{"desc": f"addr({addr})"} for addr in addresses]
        genesis_address = "1HLoD9E4SDFFPDiYfNYnkBLQ85Y51J3Zb1"
        
        # Initialize balances and errors
        balances = {addr: 0.0 for addr in addresses}
        errors = {addr: None for addr in addresses}
        
        # Add hardcoded genesis UTXO
        if genesis_address in addresses:
            balances[genesis_address] = 50.0
            print(f"Added genesis UTXO for {genesis_address}: 50.00000000 BTC (hardcoded due to Bitcoin Core limitation)")
        
        for attempt in range(3):
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
                            print(f"Found UTXOs for {addr}, total: {addr_balance:.8f} BTC")
                            utxos_for_addr = [u for u in utxos if u['desc'].split('addr(')[1].split(')')[0] == addr]
                            if utxos_for_addr:
                                utxos_for_json = [
                                    {k: float(v) if isinstance(v, Decimal) else v for k, v in u.items()}
                                    for u in utxos_for_addr[:3]
                                ]
                                print(f"Debug: First 3 UTXOs for {addr}: {json.dumps(utxos_for_json, indent=2)}")
                        balances[addr] += addr_balance
                        print(f"Debug: Total balance for {addr} after adding: {balances[addr]:.8f} BTC")
                    
                    rpc_connection.scantxoutset("abort", [])
                    return balances, errors
                else:
                    print(f"scantxoutset failed for batch")
                    return balances, {addr: "scantxoutset failed to find UTXOs" for addr in addresses}
            except (JSONRPCException, http.client.HTTPException, socket.timeout) as e:
                print(f"scantxoutset error for batch (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    return balances, {addr: f"scantxoutset failed: {e}" for addr in addresses}
    except JSONRPCException as e:
        return balances, {addr: f"RPC error: {e}" for addr in addresses}
    except Exception as e:
        return balances, {addr: f"Error checking balance: {e}" for addr in addresses}

# Function to save results to CSV with summary
def save_results(addresses, legacy_addresses, balances, errors, addr_types, statuses):
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

# Main function to process addresses, convert to legacy, and check balances
def main():
    file_path = 'bitcoin_addresses.txt'
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
    
    # Validate addresses using OpenCL
    results = opencl_validate_addresses(addresses)
    
    # Fallback to CPU if OpenCL marks addresses as invalid or fails
    if any("Invalid address" in result[1] or "OpenCL error" in result[1] for result in results):
        print("OpenCL validation failed or marked addresses as invalid, falling back to CPU-based validation...")
        results = [convert_to_legacy(addr, rpc_connection) for addr in addresses]
    
    legacy_addresses = []
    statuses = []
    addr_types = []
    valid_addresses = []
    
    # Process validation results
    for i, (legacy_address, status, addr_type, scriptpubkey) in enumerate(results):
        address = addresses[i]
        legacy_addresses.append(legacy_address)
        statuses.append(status)
        addr_types.append(addr_type)
        if legacy_address:
            valid_addresses.append(legacy_address)
        print(f"Original Address: {address}")
        print(f"Address Type: {addr_type}")
        print(f"Legacy Address: {legacy_address if legacy_address else 'N/A'}")
        print(f"Conversion Status: {status}")
        if scriptpubkey:
            print(f"ScriptPubKey: {scriptpubkey}")
        print("-" * 50)
        time.sleep(0.05)
    
    # Initialize balances and errors for all addresses
    balances = [0.0] * len(addresses)
    balance_errors = ["Skipped due to conversion failure"] * len(addresses)
    
    # Check balances in batches
    if valid_addresses:
        batch_size = 1000
        for i in range(0, len(valid_addresses), batch_size):
            batch = valid_addresses[i:i + batch_size]
            print(f"Processing batch of {len(batch)} addresses...")
            batch_balances, batch_errors = check_balance_batch(rpc_connection, batch)
            # Map batch results to original addresses
            for j, addr in enumerate(addresses):
                if addr in batch or (addr in valid_addresses and valid_addresses[j] in batch):
                    idx = valid_addresses.index(addr) if addr in valid_addresses else j
                    balances[j] = batch_balances.get(valid_addresses[idx], 0.0)
                    balance_errors[j] = batch_errors.get(valid_addresses[idx], None)
                    print(f"Debug: Assigned balance for {addr}: {balances[j]:.8f} BTC, error: {balance_errors[j]}")
                    print(f"Original Address: {addr}")
                    print(f"Balance: {balances[j]:.8f} BTC" if balances[j] is not None else f"Balance: Unable to retrieve ({balance_errors[j]})")
                    print("-" * 50)
                    time.sleep(0.05)
    else:
        for addr in addresses:
            print(f"Debug: Skipped balance check for {addr} due to conversion failure")
            print(f"Original Address: {addr}")
            print(f"Balance: 0.00000000 BTC")
            print("-" * 50)
            time.sleep(0.05)
    
    # Save results and print summary
    save_results(addresses, legacy_addresses, balances, balance_errors, addr_types, statuses)

if __name__ == "__main__":
    main()
