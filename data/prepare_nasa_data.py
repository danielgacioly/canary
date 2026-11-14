import csv,json,sys,glob,os,struct
import cdflib,numpy as np
D,RAD,OUT=sys.argv[1],sys.argv[2],sys.argv[3]
# glb info
b=open(D+"/Astronaut.glb","rb").read(); n=struct.unpack("<I",b[12:16])[0]; g=json.loads(b[20:20+n])
print("glb ext:",g.get("extensionsUsed"),"meshes",len(g.get("meshes",[])),"anims",len(g.get("animations",[])),"images",[(i.get("mimeType")) for i in g.get("images",[])])
# CBC
rows=list(csv.DictReader(open(D+"/cbc.csv",encoding="utf-8-sig")))
keys={"wbc":"white_blood_cell_count","lym":"absolute_lymphocytes","neu":"absolute_neutrophils","hgb":"hemoglobin","hct":"hematocrit","plt":"platelet_count","rbc":"red_blood_cell_count"}
cols=list(rows[0].keys())
def col(pref,kind): 
    c=[x for x in cols if x.startswith(pref+"_"+kind)]; return c[0]
order=["L-92","L-44","L-3","R+1","R+45","R+82","R+194"]
cbc={"tp":order,"an":{},"crew":{}}
for k,p in keys.items():
    v,mn,mx=col(p,"value"),col(p,"range_min"),col(p,"range_max")
    cbc["an"][k]={"unit":v.split("_value_")[1],"min":None,"max":None}
    for r in rows:
        s=r["Sample Name"].split("_"); c,tp=s[0],s[2]
        cbc["crew"].setdefault(c,{}).setdefault(k,[None]*7)
        try: cbc["crew"][c][k][order.index(tp)]=float(r[v])
        except: pass
        try: cbc["an"][k]["min"]=float(r[mn]); cbc["an"][k]["max"]=float(r[mx])
        except: pass
print(json.dumps(cbc["an"])); print(cbc["crew"]["C001"])
# DONKI
sep=json.load(open(D+"/donki_SEP.json")); gst=json.load(open(D+"/donki_GST.json")); cme=json.load(open(D+"/donki_CME.json"))
S=[{"t":e["eventTime"],"i":e["instruments"][0]["displayName"],"n":len(e.get("linkedEvents") or [])} for e in sep]
fl=sorted({l["activityID"][:16] for e in sep for l in (e.get("linkedEvents") or []) if "-FLR-" in l["activityID"]})
K=[[k["observedTime"],k["kpIndex"]] for e in gst for k in e["allKpIndex"]]
C=[]
for e in cme:
    a=[x for x in (e.get("cmeAnalyses") or []) if x.get("isMostAccurate")]
    if a and a[0].get("speed") and a[0]["speed"]>=900: C.append({"t":e["startTime"],"v":round(a[0]["speed"]),"type":a[0].get("type")})
print("fast CMEs",len(C),C[:4]); print("flares",fl)
# RAD
def series(f):
    c=cdflib.CDF(f); d=np.array(c.varget("DOSIMETRY_TOTAL"),dtype=float)[:,2]
    ep=cdflib.cdfepoch.to_datetime(c.varget("EPOCH"))
    out=[]
    for t,v in zip(ep,d):
        if 0<v<1e5:
            t=str(t); out.append([round(int(t[11:13])+int(t[14:16])/60,2),round(float(v))])
    return out
quiet=series(RAD+"/msl_rad_obs-l2_2024130_v04.cdf"); storm=series(RAD+"/msl_rad_obs-l2_2024141_v04.cdf")
print("quiet n",len(quiet),quiet[:3],"storm n",len(storm),"max",max(storm,key=lambda x:x[1]))
qm=round(sum(v for _,v in quiet)/len(quiet))
data={"cbc":cbc,"donki":{"sep":S,"flares":fl,"kp":K,"cme":C},"rad":{"quietMean":qm,"quiet":quiet[::3],"storm":storm,"unit":"µGy/dia","det":"detector E (plástico equivalente a tecido)"}}
open(OUT,"w").write("const NASA="+json.dumps(data,separators=(",",":"),ensure_ascii=False)+";")
print("bytes",os.path.getsize(OUT))
