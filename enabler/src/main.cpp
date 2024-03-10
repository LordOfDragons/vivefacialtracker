#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libusb-1.0/libusb.h>
#include <string>
#include <sstream>
#include <memory>
#include <time.h>
#include <linux/uvcvideo.h>
#include <linux/usb/video.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <vector>
#include <chrono>
#include <exception>
#include <iostream>
#include <iomanip>

class Exception{
public:
	const int rc;
	const std::string what;
	Exception(int rc, const std::string &what) : rc(rc), what(what){}
	Exception(const Exception &e) : rc(e.rc), what(e.what){}
	
	static void check(int rc, const std::string &what){
		if(rc < 0) throw Exception(rc, what);
	}
};

class ExceptionSystem{
public:
	const int rc;
	const std::string what;
	ExceptionSystem(const std::string &what) : rc(errno), what(what){}
	ExceptionSystem(const ExceptionSystem &e) : rc(e.rc), what(e.what){}
	
	static void check(bool success, const std::string &what){
		if(!success) throw ExceptionSystem(what);
	}
};

class LibUSB{
public:
	LibUSB(){
		//Exception::check(libusb_init_context(nullptr, nullptr, 0), "libusb_init");
		Exception::check(libusb_init(nullptr), "libusb_init");
	}
	
	~LibUSB(){
		libusb_exit(nullptr);
	}
};

class Device{
	LibUSB &libusb;
	libusb_device_handle *device;
	
public:
	Device(LibUSB &libusb) : libusb(libusb), device(nullptr){
		device = libusb_open_device_with_vid_pid(nullptr, 0x0bb4, 0x0321);
		if(!device){
			printf("VIVE Facial Tracker device not found.\n");
			throw Exception(LIBUSB_ERROR_NO_DEVICE, "device.open");
		}
	}
	
	~Device(){
		libusb_release_interface(device, 0);
		libusb_close(device);
	}
	
	void reset(){
		Exception::check(libusb_reset_device(device), "device.reset");
	}
	
	void claim(){
		Exception::check(libusb_set_auto_detach_kernel_driver(device, 1), "device.claim[1]");
		Exception::check(libusb_claim_interface(device, 0), "device.claim[2]");
	}
	
	void setConfiguration(int bConfigurationValue, int wIndex){
		std::stringstream ss;
		ss << "device.setConfiguration(" << bConfigurationValue << "," << wIndex << ")";
		Exception::check(libusb_control_transfer(device,
			LIBUSB_REQUEST_TYPE_STANDARD | LIBUSB_RECIPIENT_DEVICE, LIBUSB_REQUEST_SET_CONFIGURATION,
			/*wValue*/ bConfigurationValue, /*wIndex*/ wIndex, nullptr, 0, 100), ss.str());
	}
	
	void setFeature(int wFeatureSelector, int wInterface){
		std::stringstream ss;
		ss << "setFeature(" << wFeatureSelector << "," << wInterface << ")";
		Exception::check(libusb_control_transfer(device,
			LIBUSB_REQUEST_TYPE_STANDARD | LIBUSB_RECIPIENT_INTERFACE, LIBUSB_REQUEST_SET_FEATURE,
			/*wValue*/ wFeatureSelector, /*wIndex*/ wInterface, nullptr, 0, 100), ss.str());
	}
	
	void setInterface(int bAlternateSetting, int wInterface){
		std::stringstream ss;
		ss << "setInterface(" << bAlternateSetting << "," << wInterface << ")";
		Exception::check(libusb_control_transfer(device,
			LIBUSB_REQUEST_TYPE_STANDARD | LIBUSB_RECIPIENT_DEVICE, LIBUSB_REQUEST_SET_INTERFACE,
			/*wValue*/ bAlternateSetting, /*wIndex*/ wInterface, nullptr, 0, 100), ss.str());
	}
	
	void interrupt(){
		std::stringstream ss;
		ss << "interrupt(0x86)";
		Exception::check(libusb_interrupt_transfer(device, 0x86, nullptr, 0, nullptr, 100), ss.str());
	}
	
	void sleep(int msec){
		struct timespec remaining, request = { 0, msec * 1000000 }; 
		nanosleep(&request, &remaining); 
	}
};

class DataDump{
	std::vector<uint8_t> _data;
	
public:
	DataDump(size_t length, const char* dump = nullptr){
		size_t i;
		_data.assign(length, 0);
		if(dump){
			for(i=0; i<length; i++){
				_data[i] = (uint8_t)dump[i];
			}
		}
	}
	
	static DataDump withData(size_t length, const char* dump, size_t dumpLen){
		DataDump d(length);
		memcpy(d._data.data(), (const uint8_t*)dump, dumpLen);
		return d;
	}
	
	void dump() const{
		const size_t len = _data.size();
		size_t i;
		for(i=0; i<len; i++){
			printf("%02x%c", _data[i], i > 0 && (i + 1) % 16 == 0 ? '\n' : ' ');
		}
	}
	
	inline uint8_t* data(){
		return _data.data();
	}
	
	inline const uint8_t* data() const{
		return _data.data();
	}
	
	inline size_t length() const{
		return _data.size();
	}
	
	void clear(){
		memset(_data.data(), 0, _data.size());
	}
	
	void set(const char* data, size_t length){
		clear();
		memcpy(_data.data(), data, length);
	}
	
	bool operator==(const DataDump& other) const{
		return _data == other._data;
	}
};

class V4LDevice{
	int fd;
	
public:
	V4LDevice(const std::string& path) : fd(-1){
		struct stat st;
		ExceptionSystem::check(stat(path.c_str(), &st) != -1, "v4ldevice[stat]");
		ExceptionSystem::check(S_ISCHR(st.st_mode), "v4ldevice[stat.isdevice]");
		fd = open(path.c_str(), O_RDWR | O_NONBLOCK, 0);
		ExceptionSystem::check(fd != -1, "v4ldevice[open]");
	}
	
	~V4LDevice(){
		if(fd != -1){
			close(fd);
		}
	}
	
	void xuCommand(int selector, int query, int length, uint8_t *data){
		std::stringstream ss;
		ss << "v4ldevice.xuCommand(" << selector << "," << query << "," << length << ")";
		
		const uvc_xu_control_query ctrl = {
			.unit = (uint8_t)4,
			.selector = (uint8_t)selector,
			.query = (uint8_t)query,
			.size = (uint16_t)length,
			.data = data
		};
		
		ExceptionSystem::check(ioctl(fd, UVCIOC_CTRL_QUERY, &ctrl) >= 0, ss.str());
	}
	
	int xuGetLen(int selector){
		std::stringstream ss;
		ss << "v4ldevice.xuGetLen(" << selector << ")";
		
		uint16_t length = 0;
		const uvc_xu_control_query ctrl = {
			.unit = (uint8_t)4,
			.selector = (uint8_t)selector,
			.query = (uint8_t)UVC_GET_LEN,
			.size = (uint16_t)2,
			.data = (uint8_t*)&length
		};
		
		ExceptionSystem::check(ioctl(fd, UVCIOC_CTRL_QUERY, &ctrl) >= 0, ss.str());
		return length;
	}
	
	void xuGetCur(int selector, uint8_t *data, int length){
		std::stringstream ss;
		ss << "v4ldevice.xuGetCur(" << selector << "," << length << ")";
		
		const uvc_xu_control_query ctrl = {
			.unit = (uint8_t)4,
			.selector = (uint8_t)selector,
			.query = (uint8_t)UVC_GET_CUR,
			.size = (uint16_t)length,
			.data = data
		};
		
		ExceptionSystem::check(ioctl(fd, UVCIOC_CTRL_QUERY, &ctrl) >= 0, ss.str());
	}
	
	void xuGetCur(int selector, DataDump &data){
		xuGetCur(selector, data.data(), data.length());
	}
	
	void xuSetCur(int selector, const uint8_t* data, int length){
		std::stringstream ss;
		ss << "v4ldevice.xuSetCur(" << selector << "," << length << ")";
		
		const uvc_xu_control_query ctrl = {
			.unit = (uint8_t)4,
			.selector = (uint8_t)selector,
			.query = (uint8_t)UVC_SET_CUR,
			.size = (uint16_t)length,
			.data = (uint8_t*)data
		};
		
		ExceptionSystem::check(ioctl(fd, UVCIOC_CTRL_QUERY, &ctrl) >= 0, ss.str());
	}
	
	void xuSetCur(int selector, const DataDump& data){
		xuSetCur(selector, data.data(), data.length());
	}
	
	void sleep(int msec){
		struct timespec remaining, request = {msec / 1000, (msec % 1000) * 1000000}; 
		while(nanosleep(&request, &remaining)){
			request = remaining;
		}
	}
};

class ViveFacialTracker{
	std::unique_ptr<V4LDevice> _device;
	DataDump _bufferSend, _bufferReceive;
	uint8_t _bufferRegister[17];
	const bool _debug = false;
	
public:
	static const uint8_t XU_TASK_SET = 0x50;
	static const uint8_t XU_TASK_GET = 0x51;
	
	static const uint8_t XU_REG_SENSOR = 0xab;
	
	
	ViveFacialTracker() : _bufferSend(384), _bufferReceive(384){
	}
	
	void setCur(const char* log, const char* command, size_t length, size_t timeout_ms = 500){
		_ensureV4lDevice();
		_bufferSend.set(command, length);
		_device->xuSetCur(2, _bufferSend);
		if(_debug) printf("setCur(%s)\n", log);
		const auto start{std::chrono::steady_clock::now()};
		while(true){
			_bufferReceive.clear();
			_device->xuGetCur(2, _bufferReceive);
			if(_bufferReceive.data()[0] == 0x55){
				// command not finished yet
				if(_debug) printf("-> getCur: pending\n");
			}else if(_bufferReceive.data()[0] == 0x56){
				// the full command is repeated minus the last byte. we check only the first 16 bytes here
				if(memcmp(_bufferReceive.data() + 1, _bufferSend.data(), 16) == 0){
					if(_debug) printf("-> getCur: finished\n");
					return; // command finished
				}else{
					std::stringstream ss;
					ss << "ViveFacialTracker.setCur(";
					ss << log;//_streamPrintCommand(ss, command, length);
					ss << ") response not matching command: " << _bufferReceive.data()[0]
						<< " " << _bufferReceive.data()[1] << " " << _bufferReceive.data()[2];
					throw std::runtime_error(ss.str());
				}
			}else{
				std::stringstream ss;
				ss << "ViveFacialTracker.setCur(";
				ss << log; //_streamPrintCommand(ss, command, length);
				ss << ") invalid response: " << _bufferReceive.data()[0];
				throw std::runtime_error(ss.str());
			}
			
			const auto end{std::chrono::steady_clock::now()};
			const auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
			if(_debug) printf("-> elasped %zdms\n", elapsed);
			if(elapsed > timeout_ms){
				std::stringstream ss;
				ss << "ViveFacialTracker.setCur(";
				ss << log; //_streamPrintCommand(ss, command, length);
				ss << ") timeout";
				throw std::runtime_error(ss.str());
			}
		}
	}
	
	void setCur(const char* log, const DataDump& dump, size_t timeout_ms = 500){
		setCur(log, (const char*)dump.data(), dump.length(), timeout_ms);
	}
	
	int getLen(){
		_ensureV4lDevice();
		return _device->xuGetLen(2);
	}
	
	void setCurNoResp(const char* log, const char* command, size_t length){
		_ensureV4lDevice();
		_bufferSend.set(command, length);
		_device->xuSetCur(2, _bufferSend);
		if(_debug) printf("setCurNoResp(%s)\n", log);
	}
	
	void setCurNoResp(const char* log, const DataDump& dump){
		setCurNoResp(log, (const char*)dump.data(), dump.length());
	}
	
	void setRegister(const char* log, uint8_t reg, uint8_t address, uint8_t value, size_t timeout_ms = 500){
		_initRegister(XU_TASK_SET, reg, address, 1, value, 1);
		
		if(timeout_ms > 0){
			setCur(log, (const char*)_bufferRegister, sizeof(_bufferRegister), timeout_ms);
			
		}else{
			setCurNoResp(log, (const char*)_bufferRegister, sizeof(_bufferRegister));
		}
	}
	
	uint8_t getRegister(const char* log, uint8_t reg, uint8_t address, size_t timeout_ms = 500){
		_initRegister(XU_TASK_GET, reg, address, 1, 0, 1);
		
		setCur(log, (const char*)_bufferRegister, sizeof(_bufferRegister), timeout_ms);
		return _bufferReceive.data()[17];
	}
	
	void setRegisterSensor(const char* log, uint8_t address, uint8_t value, size_t timeout_ms = 500){
		setRegister(log, XU_REG_SENSOR, address, value, timeout_ms);
	}
	
	uint8_t getRegisterSensor(const char* log, uint8_t address, size_t timeout_ms = 500){
		return getRegister(log, XU_REG_SENSOR, address, timeout_ms);
	}
	
	void setEnableStream(const char* log, bool enable){
		uint8_t buf[4];
		buf[0] = XU_TASK_SET;
		buf[1] = 0x14;
		buf[2] = 0x00;
		buf[3] = enable ? 0x01 : 0x00;
		setCurNoResp(log, (const char*)buf, sizeof(buf));
	}
	
	void sleep(int msec){
		_device->sleep(msec);
	}
	
private:
	void _ensureV4lDevice(){
		if(!_device){
			_device = std::make_unique<V4LDevice>("/dev/video2");
			if(_debug) printf("device opened\n");
		}
	}
	
	void _streamPrintCommand(std::stringstream& stream, const char* command, size_t length){
		stream << std::setfill('0') << std::setw(2) << std::hex;
		size_t i;
		for(i=0; i<length; i++){
			if(i > 0){
				stream << " ";
			}
			stream << command[i];
		}
	}
	
	void _initRegister(uint8_t command, uint8_t reg, uint32_t address, uint8_t addressLen, uint32_t value, uint8_t valueLen){
		_bufferRegister[0] = command;
		_bufferRegister[1] = reg;
		_bufferRegister[2] = 0x60;
		_bufferRegister[3] = addressLen; // address width in bytes
		_bufferRegister[4] = valueLen; // data width in bytes
		
		// address
		_bufferRegister[5] = (address > 24) & 0xff;
		_bufferRegister[6] = (address > 16) & 0xff;
		_bufferRegister[7] = (address > 8) & 0xff;
		_bufferRegister[8] = address & 0xff;
		
		// page address
		_bufferRegister[9] = 0x90;
		_bufferRegister[10] = 0x01;
		_bufferRegister[11] = 0x00;
		_bufferRegister[12] = 0x01;
		
		// value
		_bufferRegister[13] = (value > 24) & 0xff;
		_bufferRegister[14] = (value > 16) & 0xff;
		_bufferRegister[15] = (value > 8) & 0xff;
		_bufferRegister[16] = value & 0xff;
	}
};

int main(int argc, char* argv[]){
	bool enable = true;
	bool reset = false;
	
	if(argc > 1){
		if(strcmp(argv[1], "--enable") == 0 || strcmp(argv[1], "-e") == 0){
			enable = true;
			
		}else if(strcmp(argv[1], "--disable") == 0 || strcmp(argv[1], "-d") == 0){
			enable = false;
			
		}else if(strcmp(argv[1], "--reset") == 0 || strcmp(argv[1], "-r") == 0){
			reset = true;
			
		}else{
			printf("Unknown parameter: '%s'\n", argv[1]);
			return 1;
		}
	}
	
	const DataDump dataCmd1(384,
		"\x51\x52\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x53\x54" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" \
		"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00");
	
	try{
		if(reset){
			printf("Reset tracker...\n");
			LibUSB libusb;
			Device device(libusb);
			device.reset();
			
		}else if(enable){
			printf("Enable tracker...\n");
			
#if 0
			LibUSB libusb;
			
			{
			Device device(libusb);
			device.claim();
			device.setConfiguration(1, 0);
			device.setFeature(/*function suspend (usb spec: endpoint halt): 0*/ 0, /*interface: 0(on) 256(off)*/ 0);
			//device.interrupt();
			}
#endif
			
			{
			ViveFacialTracker tracker;
			if(tracker.getLen() != 384){
				throw std::runtime_error("invalid length");
			}
			
			tracker.setCur("a1", dataCmd1);
			tracker.setEnableStream("a1", false);
			tracker.sleep(250);
			
			// adjust camera parameters like exposure and gain. the values used here
			// seem to be the best choices (the 3 0xff and 0xb2 ones). altering these
			// settings produces worse results
			/*{
			const uint8_t sreg1 = tracker.getRegisterSensor("a2", 0x00);
			const uint8_t sreg2 = tracker.getRegisterSensor("a3", 0x08);
			const uint8_t sreg3 = tracker.getRegisterSensor("a4", 0x70);
			const uint8_t sreg4 = tracker.getRegisterSensor("a5", 0x02);
			const uint8_t sreg5 = tracker.getRegisterSensor("a6", 0x03);
			const uint8_t sreg6 = tracker.getRegisterSensor("a7", 0x04);
			const uint8_t sreg7 = tracker.getRegisterSensor("a8", 0x0e);
			const uint8_t sreg8 = tracker.getRegisterSensor("a9", 0x05);
			const uint8_t sreg9 = tracker.getRegisterSensor("a10", 0x06);
			const uint8_t sreg10 = tracker.getRegisterSensor("a11", 0x07);
			const uint8_t sreg11 = tracker.getRegisterSensor("a12", 0x0f);
			printf("initial register values: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
				sreg1, sreg2, sreg3, sreg4, sreg5, sreg6, sreg7, sreg8, sreg9, sreg10, sreg11);
			}*/
			
			tracker.setCur("a1", dataCmd1);
			tracker.setRegisterSensor("a2", 0x00, 0x40);
			tracker.setRegisterSensor("a3", 0x08, 0x01);
			tracker.setRegisterSensor("a4", 0x70, 0x00);
			tracker.setRegisterSensor("a5", 0x02, 0xff);
			tracker.setRegisterSensor("a6", 0x03, 0xff);
			tracker.setRegisterSensor("a7", 0x04, 0xff);
			tracker.setRegisterSensor("a8", 0x0e, 0x00);
			tracker.setRegisterSensor("a9", 0x05, 0xb2);
			tracker.setRegisterSensor("a10", 0x06, 0xb2);
			tracker.setRegisterSensor("a11", 0x07, 0xb2);
			tracker.setRegisterSensor("a12", 0x0f, 0x03);
			
			/*
			tracker.setCur("b1", dataCmd1);
			tracker.setCur("b2", "\x51\xa2\x60\x04\x01\x80\x18\x11\x14\x90\x01\x00\x01\x00", 14);
			*/
			
			/*
			tracker.setCur("c1", dataCmd1);
			tracker.setCur("c2", "\x51\x02\x00", 3);  // OV580_CMD_RESET(0x02): Command to reset the OV580 using the MCU
			tracker.setCur("c3", "\x51\xa2\xc0\x04\x01\x80\x18\xff\xf0\x90\x01\x00\x01\x00", 14);
			*/
			
			tracker.setCur("d1", dataCmd1);
			tracker.setEnableStream("d2", true);
			tracker.sleep(250);
			
			// these commands are usually send grouped together
			/*
			tracker.setCur("e1", dataCmd1);
			tracker.setCur("e2", "\x51\x02\x00", 3);
			tracker.setCur("e3", "\x51\xa2\xc0\x04\x01\x80\x18\xff\xf0\x90\x01\x00\x01\x00", 14);
			*/
			}
			
#if 0
			{
			Device device(libusb);
			device.claim();
			device.setInterface(0, 1);
			}
#endif
			
		}else{
			printf("Disable tracker...\n");
			{
			ViveFacialTracker tracker;
			tracker.setCur("d1", dataCmd1);
			tracker.setEnableStream("d2", false);
			tracker.sleep(250);
			}
			
			LibUSB libusb;
			Device device(libusb);
			device.claim();
			device.setInterface(0, 1);
			device.setFeature(/*function suspend (usb spec: endpoint halt): 0*/ 0, /*interface: 0(on) 256(off)*/ 256);
		}
		
		printf("Done.\n");
		return 0;
		
	}catch(const Exception &e){
		printf("Failed: %s: %s (%d)\n", e.what.c_str(), libusb_strerror(e.rc), e.rc);
		return 1;
		
	}catch(const ExceptionSystem &e){
		printf("Failed: %s: %s (%d)\n", e.what.c_str(), strerror(e.rc), e.rc);
		return 1;
		
	}catch(const std::exception &e){
		printf("Failed: %s\n", e.what());
		return 1;
	}
}
