# %%
from IPython.display import display
from pyp9m4 import Prover9, Mace4
axioms = """
formulas(assumptions).

R(0,x,y)<->x=y.
% density
R(x,x,x).
% total symmetry
R(x,y,z)->R(y,x,z).
R(x,y,z)->R(x,z,y).
% Pasch's postulate
%(R(x,y,z) & R(z,u,v))->(exists w (R(x,u,w) & R(w,y,v))).
(exists x (R(v,w,x)&R(x,y,z)))->(exists u (R(v,u,z)&R(w,y,u))).
c=0.

end_of_list.

formulas(goals).

end_of_list.
"""
# %%
m4 = Mace4(timeout_s=100,max_models=1000)
for model in m4.models(axioms,domain_size=2):
    display(model)
    display('a model')

# %%
