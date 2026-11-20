from __future__ import annotations
import copy,hashlib,io,json,math,re,time
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode
from urllib.request import HTTPRedirectHandler,Request,build_opener
import pandas as pd
import streamlit as st
HERE=Path(__file__).resolve().parent
ALLOWED_STATES=('Andhra Pradesh','Karnataka','Kerala','Tamil Nadu')
DISCLAIMER='EXPERIMENTAL RISK SCORE \u2013 NOT A CALIBRATED FLOOD PROBABILITY'
MAP_STATUS_COLORS={
 'LOW':'#6e8b43','MODERATE':'#e8b92e','HIGH':'#bd570f','VERY HIGH':'#982f16',
 'Category withheld: low coverage':'#9b8a72','Coverage unavailable':'#706e69',
 'Score unavailable':'#8d8b86'
}
DATA=HERE/'data'; ASSET=HERE/'assets/four_state_rainfall_boundaries.geojson'
METADATA_PATH='data/dashboard_cache_metadata.json'
BOUNDARY_PATH='assets/four_state_rainfall_boundaries.geojson'
GITHUB_API='https://api.github.com'
GITHUB_API_VERSION='2022-11-28'
GITHUB_TIMEOUT_SECONDS=20
GITHUB_MAX_BYTES=100*1000*1000
GITHUB_RATE_LIMIT_RETRIES=2
GITHUB_MAX_RETRY_WAIT_SECONDS=2.0
GITHUB_API_HOST='api.github.com'
ANNUAL_REQUIRED_COLUMNS={
 'State','District','Rainfall_Boundary_Record_Index','GeoJSON_id','Target_Date',
 'Risk_Score','Risk_Category','Risk_Score_Available','Data_Quality_Status',
 'Score_Unavailable_Reason','Coverage_Gate_Status'
}
HISTORY_REQUIRED_COLUMNS={
 'state','district','Rainfall_Boundary_Record_Index','date','Rainfall_Prev_1d_mm'
}
class DataValidationError(ValueError):
 pass
class RuntimeAssetError(OSError):
 pass
class _RejectGitHubRedirectHandler(HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  raise RuntimeAssetError('GitHub API unexpectedly redirected the request; redirect was blocked.') from None
def _require_columns(frame,required,resource):
 missing=sorted(required-set(frame.columns))
 if missing:raise DataValidationError(f'{resource} is missing required columns: {", ".join(missing)}')
def _runtime_settings():
 try:runtime=st.secrets.get('runtime_assets')
 except (AttributeError,FileNotFoundError,KeyError):runtime=None
 if runtime is None:return {'mode':'local','root':HERE}
 if not hasattr(runtime,'get'):raise RuntimeAssetError('The runtime_assets Streamlit Secrets setting must be a table.')
 mode=runtime.get('mode','local')
 if mode=='local':
  root=runtime.get('local_data_root') or str(HERE)
  try:resolved_root=Path(str(root)).expanduser().resolve()
  except (OSError,RuntimeError,ValueError):raise RuntimeAssetError('The local runtime data root is invalid.') from None
  return {'mode':'local','root':resolved_root}
 if mode!='github':raise RuntimeAssetError('runtime_assets.mode must be either "local" or "github".')
 owner=runtime.get('owner');repository=runtime.get('repository');ref=runtime.get('ref')
 github=runtime.get('github',{})
 token=github.get('token') if hasattr(github,'get') else None
 if not isinstance(owner,str) or not re.fullmatch(r'[A-Za-z0-9-]+',owner):
  raise RuntimeAssetError('GitHub runtime asset owner is missing or invalid.')
 if not isinstance(repository,str) or repository in {'.','..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+',repository):
  raise RuntimeAssetError('GitHub runtime asset repository is missing or invalid.')
 if not isinstance(ref,str) or not re.fullmatch(r'[0-9a-fA-F]{40}',ref):
  raise RuntimeAssetError('GitHub runtime assets require a pinned 40-character commit SHA.')
 if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_]+',token):
  raise RuntimeAssetError('GitHub runtime asset token is missing or invalid in Streamlit Secrets.')
 prefix=_validate_path_prefix(runtime.get('path_prefix',''))
 return {'mode':'github','owner':owner,'repository':repository,'ref':ref.lower(),'path_prefix':prefix,'token':token}
def _validate_path_prefix(prefix):
 if not isinstance(prefix,str):raise RuntimeAssetError('GitHub runtime asset path_prefix must be a string.')
 if not prefix:return ''
 if prefix.startswith('/') or prefix.endswith('/') or '\\' in prefix:
  raise RuntimeAssetError('GitHub runtime asset path_prefix is invalid.')
 parts=prefix.split('/')
 if any(part in {'','.','..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+',part) for part in parts):
  raise RuntimeAssetError('GitHub runtime asset path_prefix is invalid.')
 return prefix
def _validate_asset_path(path):
 if isinstance(path,str) and path in {METADATA_PATH,BOUNDARY_PATH}:return path
 if isinstance(path,str) and re.fullmatch(r'data/annual_scores/[0-9]{4}\.csv',path):return path
 if isinstance(path,str) and re.fullmatch(r'data/district_history/[0-9]+\.csv\.gz',path):return path
 raise RuntimeAssetError('Requested runtime asset path is not in the approved asset set.')
def _asset_source(path):
 path=_validate_asset_path(path);settings=_runtime_settings()
 if settings['mode']=='local':
  root=settings['root'];local_path=(root/Path(*path.split('/'))).resolve()
  try:local_path.relative_to(root)
  except ValueError:raise RuntimeAssetError('The local runtime asset path is invalid.') from None
  stat=local_path.stat()
  return ('local',str(local_path),stat.st_mtime_ns,stat.st_size,getattr(stat,'st_ctime_ns',0),getattr(stat,'st_ino',0)),None
 return ('github',settings['owner'],settings['repository'],settings['ref'],path,settings['path_prefix']),settings['token']
def _validate_sha(value,label):
 if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{40}',value):
  raise RuntimeAssetError(f'GitHub returned an invalid {label} identifier.')
 return value.lower()
def _rate_limit_delay(headers,attempt):
 retry_after=headers.get('Retry-After')
 if retry_after is not None:
  try:delay=float(retry_after)
  except (TypeError,ValueError):return None
  return delay if 0<=delay<=GITHUB_MAX_RETRY_WAIT_SECONDS else None
 reset=headers.get('X-RateLimit-Reset')
 if reset is not None:
  try:delay=max(0.0,float(reset)-time.time())
  except (TypeError,ValueError):return None
  return delay if delay<=GITHUB_MAX_RETRY_WAIT_SECONDS else None
 return min(0.25*(2**attempt),GITHUB_MAX_RETRY_WAIT_SECONDS)
def _github_api_get(owner,repository,route,token,accept,params=None,resource='runtime resource'):
 if (not isinstance(owner,str) or not re.fullmatch(r'[A-Za-z0-9-]+',owner)
     or not isinstance(repository,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',repository)):
  raise RuntimeAssetError('GitHub runtime repository identifiers are invalid.')
 if not isinstance(route,str) or not route.startswith('/git/') or '..' in route.split('/'):
  raise RuntimeAssetError('GitHub runtime API route is invalid.')
 url=f'{GITHUB_API}/repos/{quote(owner,safe="")}/{quote(repository,safe="")}{route}'
 if params:url=f'{url}?{urlencode(params)}'
 request=Request(url,headers={
  'Authorization':f'Bearer {token}',
  'Accept':accept,
  'X-GitHub-Api-Version':GITHUB_API_VERSION,
  'User-Agent':'FloodGuardAI-runtime-asset-loader',
 })
 opener=build_opener(_RejectGitHubRedirectHandler())
 for attempt in range(GITHUB_RATE_LIMIT_RETRIES+1):
  try:
   with opener.open(request,timeout=GITHUB_TIMEOUT_SECONDS) as response:data=response.read(GITHUB_MAX_BYTES+1)
  except RuntimeAssetError:
   raise
  except HTTPError as exc:
   status=exc.code;headers=exc.headers or {}
   exc.close()
   rate_limited=(status==429 or headers.get('Retry-After') is not None or headers.get('X-RateLimit-Remaining')=='0')
   if rate_limited:
    if attempt<GITHUB_RATE_LIMIT_RETRIES:
     delay=_rate_limit_delay(headers,attempt)
     if delay is not None:
      time.sleep(delay)
      continue
    raise RuntimeAssetError('GitHub rate limit reached; retry after the limit resets.') from None
   if status==401:raise RuntimeAssetError('GitHub authentication failed; check the configured read-only token.') from None
   if status==403:raise RuntimeAssetError('GitHub denied access; check token permissions and private repository access.') from None
   if status==404:raise RuntimeAssetError(f'GitHub {resource} was not found or is inaccessible.') from None
   raise RuntimeAssetError(f'GitHub could not return the {resource} (HTTP {status}).') from None
  except (URLError,TimeoutError,ConnectionError,OSError):
   raise RuntimeAssetError('Could not reach GitHub to load a runtime resource; check network availability and retry.') from None
  if len(data)>GITHUB_MAX_BYTES:raise RuntimeAssetError('GitHub runtime blob exceeds the supported 100 MB file limit.')
  return data
 raise RuntimeAssetError('Could not load the GitHub runtime resource after bounded retries.')
@st.cache_data(ttl=3600,max_entries=8)
def _tree_for_commit(owner,repository,commit_sha,_token):
 commit_sha=_validate_sha(commit_sha,'pinned commit')
 commit_bytes=_github_api_get(owner,repository,f'/git/commits/{commit_sha}',_token,
  'application/vnd.github+json',resource='pinned commit')
 try:commit=json.loads(commit_bytes.decode('utf-8'))
 except (UnicodeError,ValueError):raise RuntimeAssetError('GitHub returned an invalid pinned commit response.') from None
 if not isinstance(commit,dict) or _validate_sha(commit.get('sha'),'commit')!=commit_sha:
  raise RuntimeAssetError('GitHub returned a commit that does not match the pinned SHA.')
 commit_tree=commit.get('tree')
 if not isinstance(commit_tree,dict):raise RuntimeAssetError('GitHub pinned commit response has no tree identifier.')
 tree_sha=_validate_sha(commit_tree.get('sha'),'tree')
 tree_bytes=_github_api_get(owner,repository,f'/git/trees/{tree_sha}',_token,
  'application/vnd.github+json',params={'recursive':'1'},resource='pinned commit tree')
 try:tree=json.loads(tree_bytes.decode('utf-8'))
 except (UnicodeError,ValueError):raise RuntimeAssetError('GitHub returned an invalid recursive tree response.') from None
 if not isinstance(tree,dict) or type(tree.get('truncated')) is not bool or not isinstance(tree.get('tree'),list):
  raise RuntimeAssetError('GitHub returned an invalid recursive tree response.')
 if tree['truncated']:
  raise RuntimeAssetError('GitHub recursive tree response is truncated; asset resolution was stopped safely.')
 if _validate_sha(tree.get('sha'),'tree')!=tree_sha:
  raise RuntimeAssetError('GitHub returned a tree that does not match the pinned commit tree.')
 blobs={}
 for entry in tree['tree']:
  if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):
   raise RuntimeAssetError('GitHub recursive tree contains an invalid entry.')
  kind=entry.get('type')
  if kind not in {'blob','tree','commit'}:
   raise RuntimeAssetError('GitHub recursive tree contains an unsupported entry type.')
  if kind=='blob':
   path=entry['path'];blob_sha=_validate_sha(entry.get('sha'),'blob')
   if path in blobs:raise RuntimeAssetError('GitHub recursive tree contains duplicate asset paths.')
   blobs[path]=blob_sha
 return blobs
def _blob_bytes(owner,repository,blob_sha,token):
 blob_sha=_validate_sha(blob_sha,'blob')
 return _github_api_get(owner,repository,f'/git/blobs/{blob_sha}',token,
  'application/vnd.github.raw+json',resource='runtime blob')
def _verify_blob_sha(data,expected_sha):
 expected_sha=_validate_sha(expected_sha,'blob')
 header=f'blob {len(data)}\0'.encode('ascii')
 actual=hashlib.sha1(header+data).hexdigest()
 if actual!=expected_sha:raise RuntimeAssetError('GitHub runtime blob failed its Git SHA-1 integrity check.')
 return data
def _read_asset(source,token):
 if source[0]=='local':return Path(source[1]).read_bytes()
 if source[0]=='github':
  _,owner,repository,commit_sha,path,path_prefix=source
  path=_validate_asset_path(path);path_prefix=_validate_path_prefix(path_prefix)
  asset_path=f'{path_prefix}/{path}' if path_prefix else path
  tree=_tree_for_commit(owner,repository,commit_sha,token)
  blob_sha=tree.get(asset_path)
  if blob_sha is None:raise RuntimeAssetError('Approved runtime asset path was not found in the pinned GitHub commit.')
  return _verify_blob_sha(_blob_bytes(owner,repository,blob_sha,token),blob_sha)
 raise RuntimeAssetError('Unknown runtime asset source.')
def _source_name(source):return Path(source[1] if source[0]=='local' else source[4]).name
@st.cache_data(ttl=3600,max_entries=4)
def _metadata_for_version(source,_token):
 data=json.loads(_read_asset(source,_token).decode('utf-8'))
 if not isinstance(data,dict):raise DataValidationError('Dashboard metadata has an invalid structure')
 required={'min_date','max_date','score_rows','unique_boundary_ids','scope_states','disclaimer','source_score_sha256','source_feature_sha256'}
 missing=sorted(required-set(data))
 if missing:raise DataValidationError(f'Dashboard metadata is missing required fields: {", ".join(missing)}')
 try:
  start=pd.Timestamp(data['min_date']);end=pd.Timestamp(data['max_date'])
 except (TypeError,ValueError) as exc:
  raise DataValidationError('Dashboard metadata contains an invalid archive date') from exc
 if pd.isna(start) or pd.isna(end) or start>end:raise DataValidationError('Dashboard metadata has an invalid archive date range')
 if not isinstance(data['scope_states'],list) or data['scope_states']!=sorted(ALLOWED_STATES):
  raise DataValidationError('Dashboard metadata has an unexpected state scope')
 if data['disclaimer']!=DISCLAIMER:raise DataValidationError('Dashboard metadata disclaimer does not match the application')
 for field in ('score_rows','unique_boundary_ids'):
  if type(data[field]) is not int or data[field]<=0:raise DataValidationError(f'Dashboard metadata has an invalid {field} value')
 return data
def metadata():
 source,token=_asset_source(METADATA_PATH)
 return _metadata_for_version(source,token)
@st.cache_data(ttl=3600,max_entries=4)
def _date_list_for_version(source,_token):
 m=_metadata_for_version(source,_token)
 return pd.date_range(m['min_date'],m['max_date'],freq='D').strftime('%Y-%m-%d').tolist()
def date_list():
 source,token=_asset_source(METADATA_PATH)
 return _date_list_for_version(source,token)
@st.cache_data(ttl=900,max_entries=4)
def _map_snapshot_for_version(year,source,_token):
 if not isinstance(year,str) or len(year)!=4 or not year.isdigit():raise ValueError('Invalid annual score year')
 filename=_source_name(source)
 frame=pd.read_csv(io.BytesIO(_read_asset(source,_token)),dtype=str,keep_default_na=False,encoding='utf-8-sig')
 _require_columns(frame,ANNUAL_REQUIRED_COLUMNS,f'Annual score file {filename}')
 if frame.empty:raise DataValidationError(f'Annual score file {filename} contains no archived records')
 if not frame.empty:
  for column in ('State','District','Rainfall_Boundary_Record_Index','GeoJSON_id','Target_Date'):
   if frame[column].eq('').any():raise DataValidationError(f'Annual score file {filename} has blank {column} identifiers')
  parsed_dates=pd.to_datetime(frame['Target_Date'],format='%Y-%m-%d',errors='coerce')
  if parsed_dates.isna().any() or not parsed_dates.dt.year.eq(int(year)).all():
   raise DataValidationError(f'Annual score file {filename} contains an invalid or mismatched target date')
  if not frame['State'].isin(ALLOWED_STATES).all():raise DataValidationError(f'Annual score file {filename} contains an out-of-scope state')
  if not frame['Risk_Score_Available'].isin({'0','1'}).all():raise DataValidationError(f'Annual score file {filename} has an invalid score-availability flag')
  if not frame['Coverage_Gate_Status'].isin({
   'PASS_AT_LEAST_80_PERCENT','FAIL_BELOW_80_PERCENT','UNAVAILABLE_COVERAGE'
  }).all():
   raise DataValidationError(f'Annual score file {filename} has an invalid coverage status')
  unavailable=frame['Risk_Score_Available'].eq('0')
  if frame.loc[unavailable,'Risk_Category'].ne('').any():raise DataValidationError(f'Annual score file {filename} assigns a category to an unavailable score')
  non_pass=~frame['Coverage_Gate_Status'].eq('PASS_AT_LEAST_80_PERCENT')
  if frame.loc[non_pass,'Risk_Category'].ne('').any():raise DataValidationError(f'Annual score file {filename} assigns a category without passing the coverage gate')
  available=frame['Risk_Score_Available'].eq('1') & ~non_pass
  if not frame.loc[available,'Risk_Category'].isin({'LOW','MODERATE','HIGH','VERY HIGH'}).all():
   raise DataValidationError(f'Annual score file {filename} has an invalid available risk category')
  meta=metadata()
  first=max(pd.Timestamp(f'{year}-01-01'),pd.Timestamp(meta['min_date']))
  last=min(pd.Timestamp(f'{year}-12-31'),pd.Timestamp(meta['max_date']))
  if first>last:raise ValueError(f'Year {year} is outside the available archive')
  expected_dates=pd.date_range(first,last).strftime('%Y-%m-%d')
  date_counts=frame.groupby('Target_Date').size()
  if len(date_counts)!=len(expected_dates) or not date_counts.index.isin(expected_dates).all() or not date_counts.eq(meta['unique_boundary_ids']).all():
   raise DataValidationError(f'Annual score file {filename} is incomplete for the archived dates')
  if frame.duplicated(['Target_Date','Rainfall_Boundary_Record_Index']).any():
   raise DataValidationError(f'Annual score file {filename} contains duplicate boundary/date records')
 return frame
def map_snapshot(year):
 if not isinstance(year,str) or len(year)!=4 or not year.isdigit():raise ValueError('Invalid annual score year')
 source,token=_asset_source(f'data/annual_scores/{year}.csv')
 return _map_snapshot_for_version(year,source,token)
@st.cache_data(ttl=900,max_entries=8)
def _district_history_for_version(boundary_id,source,_token):
 if not re.fullmatch(r'[0-9]+',str(boundary_id)):raise ValueError('Invalid rainfall boundary identifier')
 filename=_source_name(source)
 frame=pd.read_csv(io.BytesIO(_read_asset(source,_token)),dtype=str,keep_default_na=False,compression='gzip')
 _require_columns(frame,HISTORY_REQUIRED_COLUMNS,f'District history file {filename}')
 if frame.empty:raise DataValidationError(f'District history file {filename} contains no archived records')
 if not frame.empty:
  for column in ('state','district','Rainfall_Boundary_Record_Index','date'):
   if frame[column].eq('').any():raise DataValidationError(f'District history file {filename} has blank {column} identifiers')
  if not frame['state'].isin(ALLOWED_STATES).all():raise DataValidationError(f'District history file {filename} contains an out-of-scope state')
  if not frame['Rainfall_Boundary_Record_Index'].eq(str(boundary_id)).all():
   raise DataValidationError(f'District history file {filename} contains mismatched boundary identifiers')
  if frame['state'].nunique()!=1 or frame['district'].nunique()!=1:
   raise DataValidationError(f'District history file {filename} mixes district identities')
  parsed_dates=pd.to_datetime(frame['date'],format='%Y-%m-%d',errors='coerce')
  if parsed_dates.isna().any():raise DataValidationError(f'District history file {filename} contains an invalid date')
  meta=metadata()
  expected_dates=pd.date_range(meta['min_date'],meta['max_date']).strftime('%Y-%m-%d')
  if parsed_dates.dt.strftime('%Y-%m-%d').tolist()!=expected_dates.tolist():
   raise DataValidationError(f'District history file {filename} is incomplete or out of date order')
 return frame
def district_history(boundary_id):
 if not re.fullmatch(r'[0-9]+',str(boundary_id)):raise ValueError('Invalid rainfall boundary identifier')
 source,token=_asset_source(f'data/district_history/{boundary_id}.csv.gz')
 return _district_history_for_version(boundary_id,source,token)
@st.cache_resource(ttl=3600,max_entries=2)
def _boundary_geojson_for_version(source,_token):
 return json.loads(_read_asset(source,_token).decode('utf-8'))
def boundary_geojson():
 source,token=_asset_source(BOUNDARY_PATH)
 return copy.deepcopy(_boundary_geojson_for_version(source,token))
def map_rows_for_state(snapshot,state):
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 return snapshot.loc[snapshot['State'].eq(state)].copy()
def geojson_for_state(geojson,state):
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 return {**geojson,'features':[f for f in geojson.get('features',[]) if f.get('properties',{}).get('state_name')==state]}
def map_status(row):
 if row['Coverage_Gate_Status']=='FAIL_BELOW_80_PERCENT':return 'Category withheld: low coverage'
 if row['Coverage_Gate_Status']=='UNAVAILABLE_COVERAGE':return 'Coverage unavailable'
 if row['Coverage_Gate_Status']=='PASS_AT_LEAST_80_PERCENT' and row['Risk_Score_Available']=='1' and row['Risk_Category'] in {'LOW','MODERATE','HIGH','VERY HIGH'}:return row['Risk_Category']
 return 'Score unavailable'
def map_view(geojson):
 """Return a center/zoom derived from selected-state polygon coordinates."""
 positions=[]
 def walk(value):
  if isinstance(value,(list,tuple)):
   if len(value)>=2 and isinstance(value[0],(int,float)) and isinstance(value[1],(int,float)):
    lon,lat=float(value[0]),float(value[1])
    if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90:
     raise ValueError('Selected-state boundary contains invalid coordinates')
    positions.append((lon,lat))
   else:
    for item in value:walk(item)
 for feature in geojson.get('features',[]):walk(feature.get('geometry',{}).get('coordinates',[]))
 if not positions:raise ValueError('Selected-state boundary has no polygon coordinates')
 min_lon=min(p[0] for p in positions);max_lon=max(p[0] for p in positions)
 min_lat=min(p[1] for p in positions);max_lat=max(p[1] for p in positions)
 span=max(max_lon-min_lon,(max_lat-min_lat)*1.25,0.25)
 zoom=max(4.0,min(8.0,math.log2(360/span)-0.4))
 return {'lat':(min_lat+max_lat)/2,'lon':(min_lon+max_lon)/2},zoom
@st.cache_data(ttl=3600,max_entries=128)
def _cached_map_view(state,focus_district,source,_token):
 geo=geojson_for_state(_boundary_geojson_for_version(source,_token),state)
 focused=[f for f in geo.get('features',[]) if f.get('properties',{}).get('district')==focus_district]
 return map_view({**geo,'features':focused} if focused else geo)
def map_view_for_selection(state,focus_district=None):
 """Return a memoized view for the versioned, immutable Stage 10 boundary asset."""
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 source,token=_asset_source(BOUNDARY_PATH)
 return _cached_map_view(state,focus_district,source,token)
def recent_snapshot_rows(state,date_values,current_snapshot=None):
 """Read only the requested dates, loading each annual snapshot at most once."""
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 requested=tuple(dict.fromkeys(str(value) for value in date_values))
 if not requested:return pd.DataFrame()
 years=sorted({value[:4] for value in requested})
 cached_year=(str(current_snapshot['Target_Date'].iloc[0])[:4]
              if current_snapshot is not None and not current_snapshot.empty else None)
 frames=[]
 for year in years:
  snapshot=current_snapshot if year==cached_year else map_snapshot(year)
  selected=snapshot.loc[
   snapshot['Target_Date'].isin(requested)&snapshot['State'].eq(state)
  ].copy()
  if not selected.empty:frames.append(selected)
 return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
def validate_bundle(geojson=None):
 m=metadata();g=geojson if geojson is not None else boundary_geojson()
 if not isinstance(m,dict) or not isinstance(g,dict):raise DataValidationError('Regional dashboard resources have an invalid structure')
 fs=g.get('features',[])
 if m.get('scope_states')!=sorted(ALLOWED_STATES):raise ValueError('Unexpected cache scope')
 if m.get('disclaimer')!=DISCLAIMER:raise ValueError('Disclaimer mismatch')
 if not isinstance(fs,list) or len(fs)!=94:raise DataValidationError('Expected 94 validated regional boundary features')
 for feature in fs:
  if not isinstance(feature,dict) or not isinstance(feature.get('properties'),dict) or not isinstance(feature.get('geometry'),dict):
   raise DataValidationError('Regional boundary asset contains an invalid feature')
  props=feature['properties'];geometry=feature['geometry']
  if props.get('state_name') not in ALLOWED_STATES:raise DataValidationError('Regional boundary asset contains an out-of-scope state')
  if not props.get('district') or not isinstance(props.get('id'),int):raise DataValidationError('Regional boundary asset has a missing district identifier')
  if geometry.get('type') not in {'Polygon','MultiPolygon'} or not geometry.get('coordinates'):
   raise DataValidationError('Regional boundary asset contains missing or invalid geometry')
 return m
