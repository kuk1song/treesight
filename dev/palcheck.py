# usage: python3 dev/palcheck.py [palettes.json]; exits 1 if the dark set misses WCAG contrast
# quick metrics for candidate palettes: contrast vs bg, OKLab distance (normal / Machado 2009 deut, prot, trit), lightness gap
import sys, itertools
def _lin(c): return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
def rgb(h): h=h.lstrip('#'); return [_lin(int(h[i:i+2],16)/255) for i in (0,2,4)]
def Y(v): return .2126*v[0]+.7152*v[1]+.0722*v[2]
def cr(a,b): la,lb=Y(rgb(a)),Y(rgb(b)); return (max(la,lb)+.05)/(min(la,lb)+.05)
def ok(v):
    l=.4122214708*v[0]+.5363325363*v[1]+.0514459929*v[2]; m=.2119034982*v[0]+.6806995451*v[1]+.1073969566*v[2]; q=.0883024619*v[0]+.2817188376*v[1]+.6299787005*v[2]
    l,m,q=[x**(1/3) for x in (l,m,q)]
    return (.2104542553*l+.7936177850*m-.0040720468*q,1.9779984951*l-2.4285922050*m+.4505937099*q,.0259040371*l+.7827717662*m-.8086757660*q)
CVD={'deut':[[.367322,.860646,-.227968],[.280085,.672501,.047413],[-.011820,.042940,.968881]],
     'prot':[[.152286,1.052583,-.204868],[.114503,.786281,.099216],[-.003882,-.048116,1.051998]],
     'trit':[[1.255528,-.076749,-.178779],[-.078411,.930809,.147602],[.004733,.691367,.303900]]}
def sim(h,M): v=rgb(h); return [max(0,min(1,sum(M[i][j]*v[j] for j in range(3)))) for i in range(3)]
def dE(a,b,M=None):
    va,vb=(sim(a,M),sim(b,M)) if M else (rgb(a),rgb(b))
    return sum((x-y)**2 for x,y in zip(ok(va),ok(vb)))**.5
def report(name,p,bg='#0D0E11',roles=('done','found','waiting','hold')):
    print(f'== {name}  bg {bg}')
    print('  contrast', {r:round(cr(p[r],bg),2) for r in roles if r in p})
    for a,b in itertools.combinations([r for r in roles if r in p],2):
        d={k:round(dE(p[a],p[b],CVD.get(k)),3) for k in ('norm','deut','prot','trit')}
        flag=' <0.10' if min(d.values())<.1 else ''
        print(f'  {a:8s}~{b:8s}',d,flag)

# WCAG 2.2: text 4.5:1 (1.4.3), graphics that carry meaning 3:1 (1.4.11)
TEXT, GRAPHIC = ('ink','mut','faint'), ('done','found','waiting','hold','overturn','late','sess','scar_h','scar_m','scar_d')
def check(dark):
    """Return a list of failures for the dark set: text on bg and panel, graphics on bg."""
    bad=[]
    for r in TEXT:
        for surf in ('bg','panel'):
            c=cr(dark[r],dark[surf])
            if c<4.5: bad.append(f'text {r} on {surf}: {c:.2f}:1, needs 4.5')
    for r in GRAPHIC:
        c=cr(dark[r],dark['bg'])
        if c<3: bad.append(f'graphic {r} on bg: {c:.2f}:1, needs 3')
    return bad

if __name__=='__main__':
    import json, os
    path=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),'palettes.json')
    for name,sch in json.load(open(path,encoding='utf-8'))['schemes'].items():
        d=sch['dark']; report(name,d,d['bg']); bad=check(d)
        print('  text', {r:(round(cr(d[r],d['bg']),2),round(cr(d[r],d['panel']),2)) for r in TEXT})
        print('  ok' if not bad else '\n'.join('  FAIL '+b for b in bad))
        if bad: sys.exit(1)
