import hashlib
p=2**256-2**224+2**192+2**96-1
seed=bytes.fromhex("C49D360886E704936A6678E1139D26B7819F7E90")
b=0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
s=int.from_bytes(seed,'big')
h0=int.from_bytes(hashlib.sha1(seed).digest(),'big')
h1=int.from_bytes(hashlib.sha1(((s+1)%2**160).to_bytes(20,'big')).digest(),'big')
c=((h0%2**95)<<160)|h1
print(hex(c)); print((c*b*b+27)%p==0)
