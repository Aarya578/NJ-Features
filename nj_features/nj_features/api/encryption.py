import base64
from nj_features.hooks import ENCRYPTION_KEY

def xor_encrypt_decrypt(data, key):
    key = key[0]
    result = []
    for char in data:
        result.append(chr(ord(char) ^ ord(key)))
    return ''.join(result)

def encode_base64(data):
    encoded = base64.urlsafe_b64encode(data.encode()).decode()
    return encoded

def decode_base64(data):
    decoded = base64.urlsafe_b64decode(data.encode()).decode()
    return decoded

original_data = "HelloWorld"

print(f"Original Data: {original_data}")

encrypted_data = xor_encrypt_decrypt(original_data, ENCRYPTION_KEY)
print(f"Encrypted Data (Before Base64): {encrypted_data}")

alphanumeric_encrypted = encode_base64(encrypted_data)
print(f"Encrypted Data (Alphanumeric - Base64): {alphanumeric_encrypted}")

decoded_encrypted_data = decode_base64(alphanumeric_encrypted)

decrypted_data = xor_encrypt_decrypt(decoded_encrypted_data, key)
print(f"Decrypted Data: {decrypted_data}")
