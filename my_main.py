#!/usr/bin/python

import threading
import signal
import sys
#import json
import Queue
import subprocess 
import pprint as pp
from collections import namedtuple
from datetime import datetime


import MqttHandler
import PingHandler
import ProjectorHandler
import constants as c
import utility as util
import prepare_environment as env



##### GLOBAL VARS ####
global t_sniffer
t_sniffer = []
global timer_sniffer
timer_sniffer = []
global stop_list
stop_list = []
global proj_status
proj_status = False
global close_proj
close_proj = True


global sniffer_queue
sniffer_queue = Queue.Queue(c.BUF_SIZE)

StopMsg = namedtuple('StopMsg', ['mac_address', 'timestamp']) 


#close all the thread in the proper way (start when cltr-c is clicked)
def signal_handler(signal, frame):
	c.logging.info("Signal Handler arrived")
	print("Exit!")

	#close all the thread in thread list
	c.logging.debug("the thread are: %s", t_sniffer)
	
	for user in t_sniffer:
		user[0].stop()
	
	t_mqtt.stop()
	#t_proj.stop()

	
	try:
		killall_ping = subprocess.check_output(['killall', '-9', 'l2ping'], stderr=subprocess.PIPE)
		c.logging.debug("Closing l2ping process %s", killall_ping)
	except subprocess.CalledProcessError as e:
		c.logging.warning(e)
		c.logging.warning("No l2ping process")


	#close timer
	for t in timer_sniffer:
		t[0].cancel()

		
	c.logging.info("Closing the program")
	sys.exit(0)


#check if a mac_address is in the list of the active mac addresses
def is_in_list(mac_addr):
	for t in t_sniffer:
		if mac_addr in t:
			return True
	return False


#when an user arrives to the last raspberry or the timer expires
def stop_single_process(item):
	mac_target, timestamp = item
	
	if is_in_list(mac_target):
		print "stop the process ", mac_target
		c.logging.info("Stop the process %s", mac_target)

		stop_q = [q for q in stop_list if mac_target in q]
		stop_q = stop_q[0][0]
		stop_q.put(item)

		#remove old user
		for usr in stop_list:
			if mac_target in usr:
				c.logging.info("Remove user %s", usr)
				stop_list.remove(usr)

		'''
		if mac_target in projector_up:
			#delete user from list and send to projector thread
			c.logging.info("Delete projector usr %s", mac_target)
			del projector_up[mac_target]
			projector_queue.put(projector_up)
		'''

	#delete the timer
	for t in timer_sniffer:
		if mac_target in t:
			t[0].cancel()


def stop_timer(mac_addr, ts):
	print "Stop timer ", mac_addr
	c.logging.info("Stop timer %s", mac_addr)

	if is_in_list(mac_addr):
		stop_msg = StopMsg(mac_address=mac_addr, timestamp=ts)
		stop_single_process(stop_msg)
		c.logging.debug("Send stop msg in queue")

def final_pos_timer(mac_addr, ts):
	print "final position for user ", mac_addr
	c.logging.info("final position for user %s", mac_addr)

	if is_in_list(mac_addr):
		mqtt_pub_q.put(mac_addr)
		c.logging.debug("put in mqtt queue for final msg")

#return the color of a mac
def user_color(my_mac):
	for usr in t_sniffer:
		if my_mac in usr:
			return usr[2]
			
	return None

#create the thread and start the timer
#TODO: migliorare il passaggio dei parametri con my_item
def create_user(my_user):
	stop_queue = Queue.Queue(c.BUF_SIZE)
	stop_list.append([stop_queue, my_user.mac_address])
	
	user = PingHandler.PingThread(my_user, map_root, sniffer_queue, stop_queue)

	t_sniffer.append([user, my_user.mac_address, my_user.color])

	c.logging.debug("Creating a new thread")
	user.start()

	#create timer
	timer = threading.Timer(360.0, stop_timer, [my_user.mac_address, datetime.now()])
	timer.start()
	timer_sniffer.append([timer, my_user.mac_address])
	c.logging.info("New user %s!", my_user.mac_address) 
				

#### MAIN ####
if __name__ == "__main__":
	

	#initialize things
	signal.signal(signal.SIGINT, signal_handler)
	RASP_ID = env.create_path_and_files()
	util.args_parser()
	map_root = util.open_map(c.MAP)

	#the program is started
	c.logging.info("_____________________________")
	c.logging.info("SM4RT_D1R3CT10Nz v1.0 ")
	print "SM4RT_D1R3CT10Nz v1.0", 	c.RASP_ID
	c.logging.info("Starting main...")
	c.logging.info("the broker_address is "+c.BROKER_ADDRESS)



	#GLOBAL VARS
	#global projector_up
	#projector_up = {}

	#global projector_queue
	#projector_queue = Queue.Queue(c.BUF_SIZE)

	mqtt_sub_q = Queue.Queue(c.BUF_SIZE)
	mqtt_pub_q = Queue.Queue(c.BUF_SIZE)


	t_mqtt = MqttHandler.MqttThread(mqtt_sub_q, mqtt_pub_q, c.BROKER_ADDRESS)
	#t_proj = ProjectorHandler.ProjectorThread(projector_queue)
	t_mqtt.setDaemon(True)
	#t_proj.setDaemon(True)

	t_mqtt.start()
	#t_proj.start()


	while True: 
		if not mqtt_sub_q.empty():
			item = mqtt_sub_q.get()
			c.logging.info("A new message is arrived to the main. %s", item)

			if type(item).__name__ == "StartMsg":
				c.logging.info("The type is START MSG")
				c.logging.debug("Message content %s", item)

				print "The type is START MSG with mac ", item.mac_address 
			
				#check if mac is already here and add it to the list
				if not [s for s in t_sniffer if item.mac_address in s[1]]:	
					if not item.is_beacon:
						create_user(item)
					elif item.is_beacon:
						print "Create beacon user!"
						#create_user_beacon(item)

				else:
					c.logging.debug("User %s is already present", item.mac_address)

			elif type(item).__name__ == "StopMsg":
				c.logging.info("The type is STOP MSG %s", item)
				print "STOP MESSAGE", item
				
				stop_single_process(item)
				

		if not sniffer_queue.empty():
			proj_msg = sniffer_queue.get()
			c.logging.info("A projector msg is arrived")
			c.logging.debug("Reading proj queue msg: %s", proj_msg)

			if type(proj_msg).__name__ == "ProjMsg":
				c.logging.debug("The type is proj_msg")
				mac_target, direction, new_proj_status, final_pos, timestamp = proj_msg
				c.logging.debug("mac %s, dir: %s, new_proj_statu: %s, final: %s", mac_target, direction, new_proj_status, final_pos)

				if is_in_list(mac_target):
					'''
					if new_proj_status:
						c.logging.info("New image")
						if mac_target not in projector_up:
							projector_up[mac_target] = [direction, user_color(mac_target)]
							print "sendo", projector_up
							projector_queue.put(projector_up)

					if not new_proj_status:
						c.logging.info("Remove an image")
						del projector_up[mac_target]
						print "sendo", projector_up
						projector_queue.put(projector_up)
					
					'''
					if final_pos:
						print "The user is arrived to the final step, sending msg to the other sniffers..."
						c.logging.info("The user is in the final step")
						timer_final_pos = threading.Timer(20.0, final_pos_timer, [mac_target, datetime.now()])
						timer_final_pos.start()

		#delete sniffers that aren't alive			
		t_sniffer = [t for t in t_sniffer if t[0].is_alive()]

