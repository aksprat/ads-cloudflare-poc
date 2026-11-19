"""Assemble the published mock: inject mock_data.json into mock_template.html."""
import os
H=os.path.dirname(os.path.abspath(__file__)); M=os.path.join(H,'..','mock')
t=open(os.path.join(M,'mock_template.html')).read()
d=open(os.path.join(M,'mock_data.json')).read()
assert '/*DATA*/' in t
open(os.path.join(M,'edge-log-intelligence.html'),'w').write(t.replace('/*DATA*/',d))
print('wrote mock/edge-log-intelligence.html')
