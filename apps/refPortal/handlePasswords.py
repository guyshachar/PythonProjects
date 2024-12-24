from cryptography.fernet import Fernet
import json
import os
import helpers

def readReferees():
    refereeDetails = []
    readText = None
    referee_file_path = os.getenv("MY_CONFIG_FILE", f"/run/config/")
    referee_file_path = f'{referee_file_path}refereesDetails.json'
    with open(referee_file_path, 'r') as refereeDetails_file:
        readText = refereeDetails_file.read().strip()
    refereeDetails = json.loads(readText)
    return refereeDetails

def mergeReferees(referees, passwords):
    for referee in referees:
        referee['password'] = passwords[f'refId{referee['refId']}']

def writeReferees(refereeDetails):
    readText = None
    referee_file_path = os.getenv("MY_CONFIG_FILE", f"/run/config/")
    referee_file_path = f'{referee_file_path}refereesDetails.json'
    with open(referee_file_path, 'w') as refereeDetails_file:
        writeText = json.dumps(refereeDetails, ensure_ascii=False, indent=4)
        refereeDetails_file.write(writeText)

def readPasswords():
    refereeSecretsKey = helpers.get_secret('referees_passwords')#None#refPortalSecret and refPortalSecret.get("refPortal_referees", None)
    if refereeSecretsKey:
        refereeSecrets = json.loads(refereeSecretsKey)
        return refereeSecrets


def writePasswords(referees):
    with open('secret/referees_passwords1', 'w') as fields_file:
        data = json.dumps(referees, ensure_ascii=False)
        fields_file.write(data.strip())
    
def encrypt(referees):
    key = Fernet.generate_key()
    with open("secret/password_key", "wb") as key_file:
        key_file.write(key)

    # Load the key
    with open("secret/password_key", "rb") as key_file:
        key = key_file.read()

    fernet = Fernet(key)
    
    for referee in referees:
        password = referees[referee]
        encodedPassword = password.encode()
        encryptedPassword = fernet.encrypt(encodedPassword).decode("utf-8")
        referees[referee] = encryptedPassword
        print(f'{password} {encryptedPassword}')

def decryptPassword(password):
    key = helpers.get_secret('password_key')
    fernet = Fernet(key)
    decryptedPassword = fernet.decrypt(password).decode()
    return decryptedPassword

def readRefereesPasswords():
    refereesPassword = helpers.get_secret('referees_passwords')
    key = helpers.get_secret('password_key')
    fernet = Fernet(key)
    for referee in refereesPassword:
        encryptedPassword = refereesPassword[referee]
        decryptedPassword = fernet.decrypt(encryptedPassword).decode()
        refereesPassword[referee] = decryptedPassword

if __name__ == "__main__":
    referees = readReferees()
    passwords = readPasswords()
    mergeReferees(referees, passwords)
    writeReferees(referees)
    #encrypt(referees)
    #writePasswords(referees)
#    for referee in referees:
#        decryptedPassword = decryptPassword(referees[referee])
#        print(decryptedPassword)