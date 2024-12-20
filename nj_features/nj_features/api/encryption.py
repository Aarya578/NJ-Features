def encrypt(message, key):
    key_repeated = key * (len(message) // len(key)) + key[:len(message) % len(key)]
    
    encrypted_message = ''.join(chr(ord(m) ^ ord(k)) for m, k in zip(message, key_repeated))
    return encrypted_message

def decrypt(encrypted_message, key):
    return encrypt(encrypted_message, key)
