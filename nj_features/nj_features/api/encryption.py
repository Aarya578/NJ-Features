from nj_features.hooks import ENCRYPTION_KEY

class Encryption:
    
    # Function to convert binary data to hexadecimal format
    def to_hex(self, data):
        return ''.join(f'{ord(c):02x}' for c in data)
    
    # Function to convert hexadecimal string back to binary data
    def from_hex(self, hex_data):
        return ''.join(chr(int(hex_data[i:i+2], 16)) for i in range(0, len(hex_data), 2))
    
    # Encryption function using XOR cipher
    def encrypt(self, msg):
        key = ENCRYPTION_KEY
        key = (key * (len(msg) // len(key))) + key[:len(msg) % len(key)]  # Repeat the key as needed
        
        encrypted_msg = ''.join(chr(ord(msg[i]) ^ ord(key[i])) for i in range(len(msg)))
        
        return self.to_hex(encrypted_msg)
    
    # Decryption function, same as encrypt due to XOR symmetry
    def decrypt(self, msg):
        key = ENCRYPTION_KEY
        decrypted_data = self.from_hex(msg)  # Convert hex back to binary data
        
        # XOR with the key to decrypt
        key = (key * (len(decrypted_data) // len(key))) + key[:len(decrypted_data) % len(key)]  # Repeat the key
        decrypted_msg = ''.join(chr(ord(decrypted_data[i]) ^ ord(key[i])) for i in range(len(decrypted_data)))
        
        return decrypted_msg
