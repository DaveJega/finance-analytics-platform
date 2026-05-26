import streamlit_authenticator as stauth
passwords_to_hash = ['admin123']
hashed_password = stauth.Hasher(passwords_to_hash).generate()
print(hashed_password)

import streamlit_authenticator as stauth
hashed = stauth.Hasher(["yourpassword"]).generate()
print(hashed[0])

from streamlit_authenticator.utilities import Hasher

hashed = Hasher(["yourpassword"]).generate()
print(hashed[0])