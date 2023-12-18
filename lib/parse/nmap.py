import json
import time 
import xmltodict

def nmap_parser(xml_file_path):
    
    with open(xml_file_path) as xml_file:
        data_dict = xmltodict.parse(xml_file.read())
        json_data = json.dumps(data_dict)
    
    with open("/tmp/nmap-report.json", "w") as json_file:
        json_file.write(json_data)
    
    timestr = time.strftime("%Y%m%d-%H%M%S")
    
    with open(json_file.name, 'r') as file:
        data = json.load(file)

    http_identified_ports = ""

    try:
        for host in data['nmaprun']['host']:
            if 'ports' in host:
                ports_info = host['ports']
                if isinstance(ports_info.get('port'), list):
                    for port_info in ports_info['port']:
                        if isinstance(port_info, dict) and '@name' in port_info.get('service', {}) and port_info['service'].get('@name') == 'http':
                            ip = host['address']['@addr']
                            port = port_info['@portid']
                            http_identified_ports += f"{ip}:{port}\n"
                elif isinstance(ports_info.get('port'), dict):
                    port_info = ports_info['port']
                    if '@name' in port_info.get('service', {}) and port_info['service'].get('@name') == 'http':
                        ip = host['address']['@addr']
                        port = port_info['@portid']
                        http_identified_ports += f"{ip}:{port}\n" 
    
        if http_identified_ports:
            file_path = '/tmp/nmap_http_ports_extracted_for_dirsearch_'+timestr+'.txt'
            with open(file_path, 'a') as file:
                file.write(str(http_identified_ports))
                print(f"[+] Nmap report has been successfully parsed!")
                print(f"[+] Data appended to: {file_path}")
                return file_path
        else:
            print(f"[-] No HTTP identified ports found.")
            return exit(0)
        
    except Exception as e:
        print (str(e)) 