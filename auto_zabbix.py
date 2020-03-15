# -*- coding: utf-8 -*-
import sys
import os
import time
import re
import argparse
import json

def _argparse():
    parser = argparse.ArgumentParser(description="A zabbix-autodeploy tool")
    parser.add_argument('--server',action='store',dest='server',\
        default="",help="set a ZABBIX server host address.")
    parser.add_argument('--agent',action='store',dest='agent',\
        default="",help="set a ZABBIX agent host address.")
    parser.add_argument('--key_file',action='store',dest='key',\
        default="",help="give a SSH keyfile.")
    return parser.parse_args()
    

class deploy:

    def __init__(self,server_address,agent_address,key_file):
        self.server_address=self.check_address(server_address)
        self.agent_address=self.check_address(agent_address)
        self.key_file=key_file
        self.install_package('paramiko')
        self.install_package('requests')
    
    def check_address(self,ip):
        pattern=re.compile(r'(([2][0-5]{2}\.)|(\d{2}?)\.|(1\d{2}\.)|(\d\.)){3}(([2][0-5][254])|(1\d{2})|(\d{2})|(\d))')
        res=re.search(pattern,ip)
        if res:
            return res.group()
        print("Incorrect IP address format!") 
        sys.exit(0)

    def install_package(self,package_name):
        pip_list=os.popen("python -m pip list --format=columns").read()
        if package_name in pip_list:
            return True
        print("Installing package {}".format(package_name))
        res=os.popen("python -m pip install {} -i \
            https://pypi.tuna.tsinghua.edu.cn/simple".format(package_name)).read()
        if "Success" in res:
            print("package {} install success!").format(package_name)
            return True
        print("package {} install failed!").format(package_name)
        sys.exit(0)

    def get_connection(self,ip,key_file):
        import paramiko
        try:
            key=paramiko.RSAKey.from_private_key_file(key_file)
            transport=paramiko.Transport((ip,22))
            transport.connect(username='root',pkey=key)
            client=paramiko.SSHClient()
            client._transport=transport
            return client
        except Exception,e:
            print(e.message)

    def get_localip_hostip(self,connection):
        try:
            stdin,stdout,stderr=connection.exec_command("ip addr|grep -v inet6|grep inet|grep eth0|awk '{print $2}'\
                |awk -F \"/\" '{print $1}'")
            res=stdout.read()
            return res
        except Exception,e:
            print(e.message)

    def setup_zabbix_server(self,connection):
        try:
            #clean old zabbix
            _,stdout,stderr=connection.exec_command("dpkg --list|grep zabbix|\
            awk '{print $2}'|xargs -I {} dpkg --purge {}")
            stdout.read()
            stderr.read()
            _,stdout,stderr=connection.exec_command("dpkg --list|grep apache2|\
                awk '{print $2}'|xargs -I {} dpkg --purge {}")
            stdout.read()
            stderr.read()
            print("Downloading zabbix-release!")
            _,_,stderr=connection.exec_command("cd /root && \
                wget https://mirror.tuna.tsinghua.edu.cn/zabbix/zabbix/4.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_4.0-2%2Bbionic_all.deb")
            if "saved" in stderr.read():
                print("zabbix-release saved!")
                print("Installing zabbix-server!")
                _,stdout,_=connection.exec_command("cd /root && dpkg -i zabbix-release_4.0-2+bionic_all.deb")
                if "Setting up" in stdout.read():
                    _,stdout,_=connection.exec_command("apt update")
                    if "packages can be upgraded" in stdout.read():
                        print("Installing zabbix database and frontend!")
                        _,stdout,stderr=connection.exec_command("apt install -y zabbix-server-mysql && apt install -y zabbix-proxy-mysql \
                            && apt install -y zabbix-frontend-php")
                        stdout.read()
                        stderr.read()
                        _,stdout,_=connection.exec_command("dpkg --list|grep zabbix|wc -l")
                        if int(stdout.read())==4:
                            print("zabbix-server install complete!")
                            return True

            print("zabbix download or install failed! Please run this tool again!")
            sys.exit(0)
        except Exception,e:
            print(e.message)
    
    def zabbix_server_init(self,connection):
        print("zabbix database initializing")
        _,_,_,=connection.exec_command("service mysql start")
        time.sleep(15)
        _,stdout,_=connection.exec_command("mysql -uroot -Dmysql -e 'select * from user\G;'|grep zabbix")
        if stdout.read():
            _,_,_,=connection.exec_command('mysql -uroot -Dmysql -e \'drop user zabbix@localhost\'')
            _,_,_=connection.exec_command('mysql -uroot -e \'flush privileges\'')
            _,stdout,_=connection.exec_command("mysql -uroot -e 'show databases;'|grep zabbix")
            if stdout.read():
                _,_,_,=connection.exec_command('mysql -uroot -e \'DROP DATABASE zabbix\'')
        _,_,_=connection.exec_command('mysql -uroot -e \'create user \"zabbix\"@\"localhost\" identified by \"zabbix\";\'')
        _,_,_=connection.exec_command('mysql -uroot -e \'create database zabbix\'')
        _,_,_=connection.exec_command('mysql -uroot -e \'set global innodb_file_format=BARRACUDA\'')
        _,_,_=connection.exec_command('mysql -uroot -e \'set global innodb_large_prefix=on\'')
        _,_,_=connection.exec_command('mysql -uroot -e \'grant all privileges on zabbix.* to \"zabbix\"@\"localhost\"\'')
        _,_,_=connection.exec_command('cd /usr/share/doc/zabbix-server-mysql/ && gunzip create.sql.gz && \
            sed -i \'s/ENGINE=InnoDB/& ROW_FORMAT=DYNAMIC/g\' create.sql')
        _,_,_=connection.exec_command("cat /usr/share/doc/zabbix-server-mysql/create.sql \
            | mysql -uzabbix -pzabbix -Dzabbix")
        _,_,_=connection.exec_command('cd /etc/zabbix &&\
            sed -i \'s/# DBHost=localhost/DBHost=localhost/g\' zabbix-server.conf')
        _,_,_=connection.exec_command('cd /etc/zabbix &&\
            sed -i \'s/# DBPassword=/DBPassword=zabbix/g\' zabbix-server.conf')
        _,_,_=connection.exec_command('cd /etc/apache2/conf-enabled/ &&\
            sed -i \'s; # php_value date.timezone Europe/Riga;php_value date.timezone Asia/Shanghai;g\' zabbix.conf')
        _,_,_=connection.exec_command('cd /etc/apache2 &&\
            sed -i \'s/80/8080/\' ports.conf')
        _,_,_=connection.exec_command('cd /etc/apache2/site-enabled/ &&\
            sed -i \'s/80/8080/\' 000-default.conf')
        _,_,_=connection.exec_command('cd /usr/share/zabbix/ && cp setup.php setup.bak &&\
            sed -i "s/CSession::getValue(\'step\') == 5 && hasRequest(\'finish\')/CSession::getValue(\'step\') >=0/" setup.php')
        _,_,_=connection.exec_command('cd /usr/share/zabbix/conf && rm -rf zabbix.conf.php &&\
            cp zabbix.conf.php.example zabbix.conf.php &&\
                sed -i "s/\'0\'/\'3306\'/" zabbix.conf.php')
        _,_,_=connection.exec_command('cd /usr/share/zabbix/conf &&\
            sed -i "s/\'\'/\'zabbix\'/" zabbix.conf.php')
        print("zabbix database initialization complete.")
  

    def start_zabbix_server(self,connection):
        _,_,_=connection.exec_command('systemctl restart zabbix-server')
        _,_,_=connection.exec_command('update-rc.d zabbix-server enable')
        _,_,_=connection.exec_command('systemctl restart apache2')

    def setup_zabbix_agent(self,connection):
        print("setuping agent")
        _,stdout,stderr=connection.exec_command('apt install zabbix-agent')
        stdout.read()
        stderr.read()
        _,_,_=connection.exec_command('systemctl restart zabbix-agent')
    
    def close_connection(self,connection):
        connection.close()

class zabbix_operations:

    def __init__(self,host,user,password):
        self.host=host
        self.user=user
        self.password=password
        self.auth=''
        self.post_header={'Content-Type':'application/json'}
        self.url=''


    def get_url(self):
        url="http://{}:8080/zabbix/api_jsonrpc.php".format(self.host)
        self.url=url

    def identify_auth(self):
        import requests
        post_data = {
            "jsonrpc"   :   "2.0",
            "method"    :   "user.login",
            "params"    :   {
                "user"  :   "Admin",
                "password"  :   "zabbix"
            },
            "id"    :   1
        }
        ret = requests.post(self.url,data=json.dumps(post_data),headers=self.post_header)
        retobj=json.loads(ret.text)
        self.auth=retobj['result']
    
    def create_host_group(self):
        import requests
        post_data = {
            "jsonrpc"   :   "2.0",
            "method"    :   "hostgroup.create",
            "params"    :   {
                "name"  :   "test servers"
            },
            "auth"  :   self.auth,
            "id"    :   1
        }
        ret = requests.post(self.url,data=json.dumps(post_data),headers=self.post_header)
        print(json.loads(ret.text))

def main():
    parser=_argparse()
    zabbix_deploy=deploy(parser.server,parser.agent,parser.key)

    server_conn=zabbix_deploy.get_connection(zabbix_deploy.server_address,zabbix_deploy.key_file)
    agent_conn=zabbix_deploy.get_connection(zabbix_deploy.agent_address,zabbix_deploy.key_file)
    
    server_local=zabbix_deploy.get_localip_hostip(server_conn)
    print("server host ip is {} intranet ip address is {}".format(zabbix_deploy.server_address,server_local))

    agent_local=zabbix_deploy.get_localip_hostip(agent_conn)
    print("agent host ip is {} intranet ip address is {}".format(zabbix_deploy.agent_address,agent_local))

    zabbix_deploy.setup_zabbix_server(server_conn)

    zabbix_deploy.zabbix_server_init(server_conn)

    zabbix_deploy.start_zabbix_server(server_conn)

    zabbix_deploy.setup_zabbix_agent(agent_conn)

    time.sleep(15)

    zabbix_ops=zabbix_operations(zabbix_deploy.server_address,"admin","zabbix")
    zabbix_ops.get_url()
    zabbix_ops.identify_auth()
    zabbix_ops.create_host_group()
if __name__=='__main__':
    main()