def encrypt(msg, shift=4):
    encrypted_msg = []
    
    for char in msg:
        if char.isalpha():  # For letters, shift by +1
            if char.islower():
                encrypted_msg.append(chr(((ord(char) - ord('a') + shift) % 26) + ord('a')))
            else:
                encrypted_msg.append(chr(((ord(char) - ord('A') + shift) % 26) + ord('A')))
        elif char.isdigit():  # For digits, double and format with leading zero
            doubled_value = int(char) * 2
            encrypted_msg.append(f"{doubled_value:02d}")  # Ensures two-digit formatting
        else:  # Special characters remain unchanged
            encrypted_msg.append(char)
    
    return ''.join(encrypted_msg)

def decrypt(encrypted_msg, shift=4):
    decrypted_msg = []
    
    i = 0
    while i < len(encrypted_msg):
        char = encrypted_msg[i]
        if char.isalpha():  # For letters, shift by -1
            if char.islower():
                decrypted_msg.append(chr(((ord(char) - ord('a') - shift) % 26) + ord('a')))
            else:
                decrypted_msg.append(chr(((ord(char) - ord('A') - shift) % 26) + ord('A')))
            i += 1
        elif char.isdigit():  # For digits, divide by 2
            doubled_value = int(encrypted_msg[i:i+2])  # Take two digits
            decrypted_msg.append(str(doubled_value // 2))
            i += 2  # Skip over the next character because we processed two digits
        else:  # Special characters remain unchanged
            decrypted_msg.append(char)
            i += 1
    
    return ''.join(decrypted_msg)