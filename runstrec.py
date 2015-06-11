#!/usr/bin/env python

import argparse
import sys
import os.path
import urllib2
import json
import math
from datetime import datetime
from xml.dom import minidom
import StringIO

#third party libraries
from strec import cmt
import strec.utils
from strec.gmpe import GMPESelector
from neicio.cmdoutput import getCommandOutput

EVENTURL = 'http://earthquake.usgs.gov/fdsnws/event/1/query?eventid=[EVENTID]&format=geojson'
TIMEFMT = '%Y-%m-%dT%H:%M:%S'
PDLCOMMAND = '''java -jar [PDLDIR]/ProductClient.jar --send --configFile=[CONFIG] --type=strec --source=[SOURCE] --code=[CODE]  --property-latitude=[LAT] --property-longitude=[LON] --property-depth=[DEPTH] --file=[JSONFILE] [PROPS]'''

def getPlungeValues(strike,dip,rake,mag):
    mom = 10**((mag*1.5)+16.1)
    d2r = math.pi/180.0
    
    mrr=mom*math.sin(2*dip*d2r)*math.sin(rake*d2r)
    mtt=-mom*((math.sin(dip*d2r)*math.cos(rake*d2r)*math.sin(2*strike*d2r))+(math.sin(2*dip*d2r)*math.sin(rake*d2r)*(math.sin(strike*d2r)*math.sin(strike*d2r))))
    mpp=mom*((math.sin(dip*d2r)*math.cos(rake*d2r)*math.sin(2*strike*d2r))-(math.sin(2*dip*d2r)*math.sin(rake*d2r)*(math.cos(strike*d2r)*math.cos(strike*d2r))))
    mrt=-mom*((math.cos(dip*d2r)*math.cos(rake*d2r)*math.cos(strike*d2r))+(math.cos(2*dip*d2r)*math.sin(rake*d2r)*math.sin(strike*d2r)))
    mrp=mom*((math.cos(dip*d2r)*math.cos(rake*d2r)*math.sin(strike*d2r))-(math.cos(2*dip*d2r)*math.sin(rake*d2r)*math.cos(strike*d2r)))
    mtp=-mom*((math.sin(dip*d2r)*math.cos(rake*d2r)*math.cos(2*strike*d2r))+(0.5*math.sin(2*dip*d2r)*math.sin(rake*d2r)*math.sin(2*strike*d2r)))

    plungetuple = cmt.compToAxes(mrr,mtt,mpp,mrt,mrp,mtp)
    plungevals = {}
    plungevals['T'] = plungetuple[0].copy()
    plungevals['N'] = plungetuple[1].copy()
    plungevals['P'] = plungetuple[2].copy()
    plungevals['NP1'] = plungetuple[3].copy()
    plungevals['NP2'] = plungetuple[4].copy()
    return plungevals

def readQuakeML(quakeml):
    root = minidom.parse(quakeml)
    event = root.getElementsByTagName('event')[0]
    try:
        prefid = event.getElementsByTagName('preferredOriginID')[0].firstChild.data
        for origin in origins:
            if origin.getAttribute('publicID') == prefid:
                preforigin = origin
                break
    except:
        preforigin = event.getElementsByTagName('origin')[0]
        
    lat = float(preforigin.getElementsByTagName('latitude')[0].getElementsByTagName('value')[0].firstChild.data)
    lon = float(preforigin.getElementsByTagName('longitude')[0].getElementsByTagName('value')[0].firstChild.data)
    depth = float(preforigin.getElementsByTagName('depth')[0].getElementsByTagName('value')[0].firstChild.data)/1000.0
    timestr = preforigin.getElementsByTagName('time')[0].getElementsByTagName('value')[0].firstChild.data
    etime = datetime.strptime(timestr[0:19],TIMEFMT)
    try:
        prefid = event.getElementsByTagName('preferredMagnitudeID')[0].firstChild.data
        for magnitude in magnitudes:
            if magnitude.getAttribute('publicID') == prefid:
                prefmag = magnitude
                break
    except:
        prefmag = event.getElementsByTagName('magnitude')[0]
    mag = float(prefmag.getElementsByTagName('mag')[0].getElementsByTagName('value')[0].firstChild.data)
    root.unlink()
    return (lat,lon,depth,etime,mag)

def readEQXML(xmlfile):
    root = minidom.parse(quakeml)
    origin = root.getElementsByTagName('Event')[0].getElementsByTagName('Origin')[0]
    lat = float(origin.getElementsByTagName('Latitude')[0].firstChild.data)
    lon = float(origin.getElementsByTagName('Longitude')[0].firstChild.data)
    depth = float(origin.getElementsByTagName('Depth')[0].firstChild.data)
    etimestr = origin.getElementsByTagName('Time')[0].firstChild.data
    etime = datetime.strptime(etimestr[0:19],TIMEFMT)
    mag = float(origin.getElementsByTagName('Magnitude')[0].getElementsByTagName('Value')[0].firstChild.data)
    root.unlink()
    return (lat,lon,depth,etime,mag)

def getMT(eventid):
    url = EVENTURL.replace('[EVENTID]',eventid)
    fh = urllib2.urlopen(url)
    data = fh.read()
    fh.close()
    jdict = json.loads(data)
    if 'moment-tensor' not in jdict['properties']['products'].keys():
        return None
    tensor = jdict['properties']['products']['moment-tensor'][0] #assume first one is best
    T = {}
    T['azimuth'] = float(tensor['properties']['t-axis-azimuth'])
    T['plunge'] = float(tensor['properties']['t-axis-plunge'])
    N = {}
    N['azimuth'] = float(tensor['properties']['n-axis-azimuth'])
    N['plunge'] = float(tensor['properties']['n-axis-plunge'])
    P = {}
    P['azimuth'] = float(tensor['properties']['p-axis-azimuth'])
    P['plunge'] = float(tensor['properties']['p-axis-plunge'])
    NP1 = {}
    NP1['strike'] = float(tensor['properties']['nodal-plane-1-strike'])
    NP1['dip'] = float(tensor['properties']['nodal-plane-1-dip'])
    NP1['rake'] = float(tensor['properties']['nodal-plane-1-rake'])
    NP2 = {}
    NP2['strike'] = float(tensor['properties']['nodal-plane-2-strike'])
    NP2['dip'] = float(tensor['properties']['nodal-plane-2-dip'])
    NP2['rake'] = float(tensor['properties']['nodal-plane-2-rake'])
    return {'NP1':NP1,'NP2':NP2,'T':T,'N':N,'P':P}

def getVersionFolder(homedir,eventid):
    outfolder = os.path.join(homedir,'strec_output')
    if not os.path.isdir(outfolder):
        os.makedirs(outfolder)
    eventfolder = os.path.join(outfolder,eventid)
    if not os.path.isdir(eventfolder):
        versionfolder = os.path.join(eventfolder,'version001')
    else:
        highest = 0
        previous = os.listdir(eventfolder)
        for tfolder in previous:
            if not tfolder.startswith('version'):
                continue
            vfolder = os.path.join(eventfolder,tfolder)
            if int(vfolder[-3:]) > highest:
                highest = int(vfolder[-3:])
        versionfolder = os.path.join(eventfolder,'version%03i' % (highest+1))
    os.makedirs(versionfolder)
    return versionfolder

def main(args):
    isDev = True
    #Get the user parameters config object (should be stored in ~/.strec/strec.ini)
    try:
        config,configfile = strec.utils.getConfig()
    except Exception,msg:
        print msg
        sys.exit(1)

    if config is None:
        print 'Could not find a configuration file.  Run strec_init.py to create it.'
        sys.exit(0)
    
    datafolder = config.get('DATA','folder')
    gcmtfile = os.path.join(datafolder,strec.utils.GCMT_OUTPUT)
    
    if args.status == 'DELETE':
        print 'Not currently processing deletes.'
        sys.exit(0)
    if args.type not in ['origin','phase-data']:
        print 'Not currently processing deletes.'
        sys.exit(0)
    pfolder = args.directory
    quakeml = os.path.join(pfolder,'quakeml.xml')
    eqxml = os.path.join(pfolder,'eqxml.xml')
    hasquakeml = os.path.isfile(quakeml)
    haseqxml = os.path.isfile(eqxml)
    eventid = args.source + args.code
    if not hasquakeml and not haseqxml:
        print 'Origin products must be specified in either EQXML or QuakeML formats.'
        sys.exit(1)
    if hasquakeml:
        lat,lon,depth,etime,mag = readQuakeML(quakeml)
    else:
        lat,lon,depth,etime,mag = readEQXML(quakeml)
    
    plungevals = getMT(eventid)
    forceComposite = True
    if plungevals is not None:
        forceComposite = False

    gs = GMPESelector(configfile,gcmtfile,datafolder)
    strecresults = gs.selectGMPE(lat,lon,depth,mag,date=etime,
                                 forceComposite=forceComposite,
                                 plungevals=plungevals)
    jsonstr = StringIO.StringIO()
    strecresults.renderGeoJSON(jsonstr)
    homedir = os.path.expanduser('~')
    pdldir = os.path.join(homedir,'ProductClient')
    if isDev:
        configfile = os.path.join(pdldir,'dev_config.ini')
    else:
        configfile = os.path.join(pdldir,'config.ini')
    versionfolder = getVersionFolder(homedir,eventid)
    jsonfile = os.path.join(versionfolder,'strec.json')
    f = open(jsonfile,'wt')
    f.write(jsonstr.getvalue())
    f.close()
    cmd = PDLCOMMAND.replace('[PDLDIR]',pdldir)
    cmd = cmd.replace('[CONFIG]',configfile)
    cmd = cmd.replace('[SOURCE]',args.source)
    cmd = cmd.replace('[CODE]',eventid)
    cmd = cmd.replace('[LAT]','%.4f' % lat)
    cmd = cmd.replace('[LON]','%.4f' % lon)
    cmd = cmd.replace('[DEPTH]','%.1f' % depth)
    cmd = cmd.replace('[JSONFILE]',jsonfile)
    jdict = json.loads(jsonstr.getvalue())
    propnuggets = []
    for propkey,propvalue in jdict['properties'].iteritems():
        prop = '--property-%s="%s"' % (propkey,str(propvalue))
        propnuggets.append(prop)
    propstr = ' '.join(propnuggets)
    cmd = cmd.replace('[PROPS]',propstr)
    res,stdout,stderr = getCommandOutput(cmd)
    if not res:
        print 'Command %s failed.' % cmd
    else:
        print 'Command %s succeeded.' % cmd
    print stdout
    print stderr
    
    
    
        
if __name__ == '__main__':
    usage = """Run STREC from PDL."""
    parser = argparse.ArgumentParser(description=usage)
    parser.add_argument('--directory',help='Directory containing origin data')
    parser.add_argument('--type',help='PDL product type')
    parser.add_argument('--code',help='PDL product code (not including source network)')
    parser.add_argument('--source',help='PDL product source (source + code = id)')
    parser.add_argument('--status',help='PDL product status (UPDATE or DELETE)')
    pargs, unknown = parser.parse_known_args()
    main(pargs)
