from __future__ import annotations
import copy,json,math
from pathlib import Path
import pandas as pd
import streamlit as st
HERE=Path(__file__).resolve().parent
ALLOWED_STATES=('Andhra Pradesh','Karnataka','Kerala','Tamil Nadu')
DISCLAIMER='EXPERIMENTAL RISK SCORE \u2013 NOT A CALIBRATED FLOOD PROBABILITY'
MAP_STATUS_COLORS={
 'LOW':'#6e8b43','MODERATE':'#e8b92e','HIGH':'#bd570f','VERY HIGH':'#982f16',
 'Category withheld: low coverage':'#9b8a72','Score unavailable':'#8d8b86'
}
DATA=HERE/'data'; ASSET=HERE/'assets/four_state_rainfall_boundaries.geojson'
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
def _require_columns(frame,required,resource):
 missing=sorted(required-set(frame.columns))
 if missing:raise DataValidationError(f'{resource} is missing required columns: {", ".join(missing)}')
def _file_version(path):
 stat=path.stat()
 return stat.st_mtime_ns,stat.st_size,getattr(stat,'st_ctime_ns',0),getattr(stat,'st_ino',0)
@st.cache_data(ttl=3600,max_entries=4)
def _metadata_for_version(modified_ns,size_bytes,changed_ns,file_id):
 data=json.loads((DATA/'dashboard_cache_metadata.json').read_text(encoding='utf-8'))
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
 return _metadata_for_version(*_file_version(DATA/'dashboard_cache_metadata.json'))
@st.cache_data(ttl=3600,max_entries=4)
def _date_list_for_version(modified_ns,size_bytes,changed_ns,file_id):
 m=_metadata_for_version(modified_ns,size_bytes,changed_ns,file_id)
 return pd.date_range(m['min_date'],m['max_date'],freq='D').strftime('%Y-%m-%d').tolist()
def date_list():
 return _date_list_for_version(*_file_version(DATA/'dashboard_cache_metadata.json'))
@st.cache_data(ttl=900,max_entries=4)
def _map_snapshot_for_version(year,modified_ns,size_bytes,changed_ns,file_id):
 if not isinstance(year,str) or len(year)!=4 or not year.isdigit():raise ValueError('Invalid annual score year')
 p=DATA/'annual_scores'/f'{year}.csv'
 frame=pd.read_csv(p,dtype=str,keep_default_na=False,encoding='utf-8-sig')
 _require_columns(frame,ANNUAL_REQUIRED_COLUMNS,f'Annual score file {p.name}')
 if frame.empty:raise DataValidationError(f'Annual score file {p.name} contains no archived records')
 if not frame.empty:
  for column in ('State','District','Rainfall_Boundary_Record_Index','GeoJSON_id','Target_Date'):
   if frame[column].eq('').any():raise DataValidationError(f'Annual score file {p.name} has blank {column} identifiers')
  parsed_dates=pd.to_datetime(frame['Target_Date'],format='%Y-%m-%d',errors='coerce')
  if parsed_dates.isna().any() or not parsed_dates.dt.year.eq(int(year)).all():
   raise DataValidationError(f'Annual score file {p.name} contains an invalid or mismatched target date')
  if not frame['State'].isin(ALLOWED_STATES).all():raise DataValidationError(f'Annual score file {p.name} contains an out-of-scope state')
  if not frame['Risk_Score_Available'].isin({'0','1'}).all():raise DataValidationError(f'Annual score file {p.name} has an invalid score-availability flag')
  if not frame['Coverage_Gate_Status'].isin({'PASS_AT_LEAST_80_PERCENT','FAIL_BELOW_80_PERCENT'}).all():
   raise DataValidationError(f'Annual score file {p.name} has an invalid coverage status')
  unavailable=frame['Risk_Score_Available'].eq('0')
  if frame.loc[unavailable,'Risk_Category'].ne('').any():raise DataValidationError(f'Annual score file {p.name} assigns a category to an unavailable score')
  gated=frame['Coverage_Gate_Status'].eq('FAIL_BELOW_80_PERCENT')
  if frame.loc[gated,'Risk_Category'].ne('').any():raise DataValidationError(f'Annual score file {p.name} assigns a category below the coverage gate')
  available=frame['Risk_Score_Available'].eq('1') & ~gated
  if not frame.loc[available,'Risk_Category'].isin({'LOW','MODERATE','HIGH','VERY HIGH'}).all():
   raise DataValidationError(f'Annual score file {p.name} has an invalid available risk category')
  meta=metadata()
  first=max(pd.Timestamp(f'{year}-01-01'),pd.Timestamp(meta['min_date']))
  last=min(pd.Timestamp(f'{year}-12-31'),pd.Timestamp(meta['max_date']))
  if first>last:raise ValueError(f'Year {year} is outside the available archive')
  expected_dates=pd.date_range(first,last).strftime('%Y-%m-%d')
  date_counts=frame.groupby('Target_Date').size()
  if len(date_counts)!=len(expected_dates) or not date_counts.index.isin(expected_dates).all() or not date_counts.eq(meta['unique_boundary_ids']).all():
   raise DataValidationError(f'Annual score file {p.name} is incomplete for the archived dates')
  if frame.duplicated(['Target_Date','Rainfall_Boundary_Record_Index']).any():
   raise DataValidationError(f'Annual score file {p.name} contains duplicate boundary/date records')
 return frame
def map_snapshot(year):
 if not isinstance(year,str) or len(year)!=4 or not year.isdigit():raise ValueError('Invalid annual score year')
 p=DATA/'annual_scores'/f'{year}.csv'
 return _map_snapshot_for_version(year,*_file_version(p))
@st.cache_data(ttl=900,max_entries=8)
def _district_history_for_version(boundary_id,modified_ns,size_bytes,changed_ns,file_id):
 if not str(boundary_id).isdigit():raise ValueError('Invalid rainfall boundary identifier')
 p=DATA/'district_history'/f'{boundary_id}.csv.gz'
 frame=pd.read_csv(p,dtype=str,keep_default_na=False,compression='gzip')
 _require_columns(frame,HISTORY_REQUIRED_COLUMNS,f'District history file {p.name}')
 if frame.empty:raise DataValidationError(f'District history file {p.name} contains no archived records')
 if not frame.empty:
  for column in ('state','district','Rainfall_Boundary_Record_Index','date'):
   if frame[column].eq('').any():raise DataValidationError(f'District history file {p.name} has blank {column} identifiers')
  if not frame['state'].isin(ALLOWED_STATES).all():raise DataValidationError(f'District history file {p.name} contains an out-of-scope state')
  if not frame['Rainfall_Boundary_Record_Index'].eq(str(boundary_id)).all():
   raise DataValidationError(f'District history file {p.name} contains mismatched boundary identifiers')
  if frame['state'].nunique()!=1 or frame['district'].nunique()!=1:
   raise DataValidationError(f'District history file {p.name} mixes district identities')
  parsed_dates=pd.to_datetime(frame['date'],format='%Y-%m-%d',errors='coerce')
  if parsed_dates.isna().any():raise DataValidationError(f'District history file {p.name} contains an invalid date')
  meta=metadata()
  expected_dates=pd.date_range(meta['min_date'],meta['max_date']).strftime('%Y-%m-%d')
  if parsed_dates.dt.strftime('%Y-%m-%d').tolist()!=expected_dates.tolist():
   raise DataValidationError(f'District history file {p.name} is incomplete or out of date order')
 return frame
def district_history(boundary_id):
 if not str(boundary_id).isdigit():raise ValueError('Invalid rainfall boundary identifier')
 p=DATA/'district_history'/f'{boundary_id}.csv.gz'
 return _district_history_for_version(boundary_id,*_file_version(p))
@st.cache_resource(ttl=3600,max_entries=2)
def _boundary_geojson_for_version(modified_ns,size_bytes,changed_ns,file_id):
 return json.loads(ASSET.read_text(encoding='utf-8'))
def boundary_geojson():
 return copy.deepcopy(_boundary_geojson_for_version(*_file_version(ASSET)))
def map_rows_for_state(snapshot,state):
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 return snapshot.loc[snapshot['State'].eq(state)].copy()
def geojson_for_state(geojson,state):
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 return {**geojson,'features':[f for f in geojson.get('features',[]) if f.get('properties',{}).get('state_name')==state]}
def map_status(row):
 if row['Coverage_Gate_Status']=='FAIL_BELOW_80_PERCENT':return 'Category withheld: low coverage'
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
def _cached_map_view(state,focus_district,modified_ns,size_bytes,changed_ns,file_id):
 geo=geojson_for_state(boundary_geojson(),state)
 focused=[f for f in geo.get('features',[]) if f.get('properties',{}).get('district')==focus_district]
 return map_view({**geo,'features':focused} if focused else geo)
def map_view_for_selection(state,focus_district=None):
 """Return a memoized view for the versioned, immutable Stage 10 boundary asset."""
 if state not in ALLOWED_STATES:raise ValueError(f'Out-of-scope state: {state}')
 return _cached_map_view(state,focus_district,*_file_version(ASSET))
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
