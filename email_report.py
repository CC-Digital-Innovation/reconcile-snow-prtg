import configparser
import smtplib
import ssl
from email.message import EmailMessage
from itertools import zip_longest
from pathlib import PurePath
from tabulate import tabulate

# read and parse config file
config = configparser.ConfigParser()
config_path = PurePath(__file__).parent / 'config.ini'
config.read(config_path)

smtp_server = config['email']['server']
port = config['email']['port']
password = config['email']['password']
sender_email = config['email']['from']

context = ssl.create_default_context()

def send_digest(digest):
    message = digest_to_html(digest)
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        for receiver in config['email']['to'].split(','):
            msg = EmailMessage()
            msg['Subject'] = 'Digest Report'
            msg['From'] = sender_email
            msg['To'] = receiver
            msg.add_alternative(message, subtype='html')
            server.login(sender_email, password)
            server.send_message(msg)

def digest_to_html(digest):
    good = []
    bad = []
    unknown = []
    for report in digest:
        #TODO switch to EAFP when cmdb is more reliable
        if 'result' in digest[report] and digest[report]['result'] is not None:
            if digest[report]['result'] > 0:
                bad.append(report)
            elif digest[report]['result'] == 0:
                good.append(report)
            elif 'unknown' in digest[report]:
                unknown.append(report)
    builder = [f'''
        <html>
        <head>
            <style>
                caption {{ font-weight: bold; font-size: 1.2em; }}
                table {{ width: 100%; }}
                table, th, td {{ border: 1px solid black; border-collapse: collapse; }}
                th, td {{ padding: 5px; }}
            </style>
        </head>
        <body>
        <table>
        <caption>Reconcile Report of All Devices</caption>
        <thead>
            <tr>
                <th>&#9989; No Issues ({len(good)})</th>
                <th>&#10060; Missing/Mismatches ({len(bad)})</th>
                <th>&#10071; Failed to Check ({len(unknown)})</th>
            </tr>
        </thead>
        <tbody>
        ''']
    for g, b, u in zip_longest(good, bad, unknown):
        builder.append(f'<tr>')
        if g:
            builder.append(f'<td>[{digest[g]["company"]}] {digest[g]["site"]}</td>')
        else:
            builder.append(f'<td>&nbsp;</td>')
        if b:
            builder.append(f'<td>[{digest[b]["company"]}] {digest[b]["site"]} ({digest[b]["result"]})</td>')
        else:
            builder.append(f'<td>&nbsp;</td>')
        if u:
            builder.append(f'<td>[{digest[u]["company"]}] {digest[u]["site"]}</td>')
        else:
            builder.append(f'<td>&nbsp;</td>')
        builder.append('</tr>')
    builder.append('''
        </tbody>
        </table>
        </body>
        </html>''')
    return ''.join(builder)

def send_report(company_name, site_name, missing_in_prtg, missing_in_snow, mismatch):
    message = report_to_html(company_name, site_name, missing_in_prtg, missing_in_snow, mismatch)
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        for receiver in config['email']['to'].split(','):
            msg = EmailMessage()
            msg['Subject'] = f'Reconcile Report - {company_name} at {site_name}'
            msg['From'] = sender_email
            msg['To'] = receiver
            msg.add_alternative(message, subtype='html')
            server.login(sender_email, password)
            server.send_message(msg)

def report_to_html(company_name, site_name, missing_in_prtg, missing_in_snow, mismatch):
    builder = ['''
        <html>
        <head>
            <style>
                table, th, td { border: 1px solid black; border-collapse: collapse; }
                th, td { padding: 5px; }
            </style>
        </head>
        <body>
        ''']
    builder.append(f'<h2>Checking devices from {company_name} at {site_name}</h2>')
    if missing_in_prtg:
        builder.append('<h3>Missing devices in PRTG:</h3>')
        builder.append(tabulate(missing_in_prtg, headers=['Device Name', 'Link'], tablefmt='html'))
    else:
        builder.append('<h3>No devices missing in PRTG!</h3>')
    if missing_in_snow:
        builder.append('<h3>Missing devices in SNOW:</h3>')
        builder.append(tabulate(missing_in_snow, headers=['Device Name', 'Link'], tablefmt='html'))
    else:
        builder.append('<h3>No devices missing in SNOW!</h3>')
    if mismatch:
        builder.append('<h3>Devices with mismatched fields:</h3>')
        for device in mismatch:
            builder.append(f'''
                <table>
                <caption>PRTG Name: <a href="{device["prtg_link"]}">{device["prtg_device"]}</a><br/>SNOW Name: <a href="{device["snow_link"]}">{device["snow_device"]}</a></caption>
                <thead>
                    <tr>
                        <th>Field</th>
                        <th>PRTG Value</th>
                        <th>SNOW Value</th>
                    </tr>
                </thead>
                <tbody>''')
            for field_name, fields in device['fields'].items():
                builder.append(f'''
                    <tr>
                        <td>{field_name}</td>
                        <td>{fields["prtg"]}</td>
                        <td>{fields["snow"]}</td>
                    </tr>''')
            builder.append('''
                </tbody>
                </table>''')
    else:
        builder.append('<h3>No mismatches found!</h3>')
    builder.append('</body></html>')
    return ''.join(builder)