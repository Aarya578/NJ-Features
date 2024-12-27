def encrypt_decrypt(input_string, key):
    output = ''.join(chr(ord(char) ^ key) for char in input_string)
    return output
