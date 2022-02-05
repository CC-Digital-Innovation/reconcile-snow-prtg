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
user = config['email']['user']
password = config['email']['password']
sender_email = config['email']['from']
receiver = config['email']['to']

context = ssl.create_default_context()

def send_email(subject, message):
    # create message
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver
    msg.set_content('''Report is create and sent as an HTML, and is only visibile with clients that can render HTML emails.
                       Contact at jonny.le@computacenter.com if there are any issues.''')
    msg.add_alternative(message, subtype='html')
    with smtplib.SMTP(smtp_server, port) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)

def send_digest(digest):
    message = digest_to_html(digest)
    subject = 'Digest Report'
    send_email(subject, message)

def digest_to_html(digest):
    good = []
    bad = []
    error = []
    for report in digest:
        if 'result' in report:
            if report['result']:
                bad.append(report)
            elif report['result'] == 0:
                good.append(report)
        elif 'error' in report:
            error.append(report)
    builder = [f'''\
        <!DOCTYPE html>
        <html>
        <head>
        <title>Reconcile - Digest Report</title>
        <style>
            caption {{ 
                font-weight: bold; 
            }}
            table {{
                border-collapse: collapse;
            }}
            th {{
                border: 1px solid black;
                padding: 3px;
                background-color: #08088A;
                color: white;
                font-size: 100%;
            }}
            td {{
                border: 1px solid black;
                padding: 3px;
                font-size: 100%;
            }}
        </style>
        </head>
        <body>
        <table>
        <caption>Reconcile Report of All Devices</caption>
        <thead>
            <tr>
                <th>&#9989; No Issues ({len(good)})</th>
                <th>&#10060; Missing/Mismatches ({len(bad)})</th>
                <th>&#10071; Failed to Check ({len(error)})</th>
            </tr>
        </thead>
        <tbody>
        ''']
    for g, b, e in zip_longest(good, bad, error):
        builder.append('<tr>')
        if g:
            builder.append(f'<td>[{g["company"]}] {g["site"]}</td>')
        else:
            builder.append(f'<td></td>')
        if b:
            builder.append(f'<td>[{b["company"]}] {b["site"]} ({b["result"]})</td>')
        else:
            builder.append(f'<td></td>')
        if e:
            builder.append(f'<td>[{e["company"]}] {e["site"]}</td>')
        else:
            builder.append(f'<td></td>')
        builder.append('</tr>')
    builder.append('''
        </tbody>
        </table>''')
    if error:
        builder.append('<h4>Logs</h4><p>')
        for e in error:
            builder.append(f'[{e["company"]}] {e["site"]}: {e["error"]}<br/>')
        builder.append('</p>')
    builder.append('''
        </body>
        </html>''')
    return ''.join(builder)

def send_report(company_name, site_name, missing_in_prtg, missing_in_snow, mismatch):
    message = report_to_html(company_name, site_name, missing_in_prtg, missing_in_snow, mismatch)
    subject = f'Reconcile Report - {company_name} at {site_name}'
    send_email(subject, message)

def report_to_html(company_name, site_name, missing_in_prtg, missing_in_snow, mismatch):
    builder = ['''\
        <!DOCTYPE html>
        <html>
        <head>
        <title>Reconcile Report</title>
        <style>
            caption {
                font-weight: bold; 
            }
            table {
                border-collapse: collapse;
            }
            th {
                border: 1px solid black;
                padding: 3px;
                background-color: #08088A;
                color: white;
                font-size: 100%;
            }
            td {
                border: 1px solid black;
                padding: 3px;
                font-size: 100%;
            }
        </style>
        </head>
        <body>
        ''']
    builder.append(f'<h1>{company_name} at {site_name}</h1>')
    if missing_in_prtg:
        builder.append('<h2>Missing devices in PRTG:</h2>')
        builder.append(tabulate(missing_in_prtg, headers=['Device Name', 'Link'], tablefmt='html'))
    if missing_in_snow:
        builder.append('<h2>Missing devices in SNOW:</h2>')
        builder.append(tabulate(missing_in_snow, headers=['Device Name', 'Link'], tablefmt='html'))
    if mismatch:
        builder.append('<h2>Devices with mismatched fields:</h2>')
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
    builder.append('</body></html>')
    return ''.join(builder)

def send_missing_list(company_name, site_name, missing_list):
    message = missing_fields_to_html(company_name, site_name, missing_list)
    subject = 'Couldn\'t Initialize PRTG'
    send_email(subject, message)

def missing_fields_to_html(company_name, site_name, missing_list):
    builder = ['''\
        <!DOCTYPE html>
        <html>
        <head>
        <title>Automated PRTG Deployment</title>
        <style>
            caption {
                font-weight: bold; 
            }
            table {
                border-collapse: collapse;
            }
            th {
                border: 1px solid black;
                padding: 3px;
                background-color: #08088A;
                color: white;
                font-size: 100%;
            }
            td {
                border: 1px solid black;
                padding: 3px;
                font-size: 100%;
            }
        </style>
        </head>
        <body>
        ''']
    builder.append(f'''
        <h2>Unable to initialize PRTG for {company_name} at {site_name} because required fields are missing. Please fix the issues and retry.</h2>
        <p style="color: red;">*Required</p>''')
    for missing in missing_list:
        builder.append(f'''
            <h4><a href="{missing["link"]}">{missing["name"]}</a></h4>
            <ul>''')
        for field in missing['errors']:
            builder.append(f'<li><span style="color: red;">*{field}</span></li>')
        for field in missing['warnings']:
            builder.append(f'<li>{field}</li>')
        builder.append('</ul>')
    builder.append('</body></html>')
    return ''.join(builder)

def send_success_init_prtg(company_name, site_name, created_list, missing_list):
    message = init_to_html(company_name, site_name, created_list, missing_list)
    subject = 'Successfully Initialized PRTG Structure.'
    send_email(subject, message)

def init_to_html(company_name, site_name, created_list, missing_list):
    builder = [f'''\
        <!DOCTYPE html>
        <html>
        <head>
        <title>Automated PRTG Deployent</title>
        <style>
            caption {{
                font-weight: bold; 
            }}
            table {{
                border-collapse: collapse;
            }}
            th {{
                border: 1px solid black;
                padding: 3px;
                background-color: #08088A;
                color: white;
                font-size: 100%;
            }}
            td {{
                border: 1px solid black;
                padding: 3px;
                font-size: 100%;
            }}
        </style>
        </head>
        <body>
            <h1>Successfully created the PRTG structure for {company_name} at {site_name}.</h1>
            <table>
            <caption>Devices Added to PRTG</caption>
            <thead>
                <tr>
                    <th style="border-top: 0; border-left: 0; background-color: transparent;"></th>
                    <th>PRTG Name</th>
                    <th>SNOW Name</th>
                </tr>
            </thead>
            <tbody>''']
    for i, device in enumerate(created_list, start=1):
        builder.append(f'''
            <tr>
                <td>{i}.</td>
                <td><a href="{device['prtg_link']}">{device['prtg']}</a></td>
                <td><a href="{device['snow_link']}">{device['snow']}</a></td>
            </tr>''')
    builder.append('''
        </tbody>
        </table>''')
    if missing_list:
        builder.append('<h2>Missing Optional Fields</h2>')
    for missing in missing_list:
        builder.append(f'''
            <h4><a href="{missing["link"]}">{missing["name"]}</a></h4>
            <ul>''')
        for field in missing['warnings']:
            builder.append(f'<li>{field}</li>')
        builder.append('</ul>')
    builder.append('</body></html>')
    return ''.join(builder)
