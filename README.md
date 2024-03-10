# VIVE Facial Tracker Test App
Test app to stream from VIVE Facial Tracker under Linux.


# Test App - Prepare

To run the test app prepare a python virtual environment like this:
> python -m venv venv_vftta

Enter the virtual environment:
> source venv_vftta/bin/activate

Install the required packages:
> python -m pip install --upgrade toga numpy Pillow v4l2py opencv-python

Run the application:
> cd src
> python3 -m testapp

Select the video device of the VIVE Facial Tracker. Usually this is 2
which refers to /dev/video2 . See the information section for more details.

Enable now the camera and you should see the stream.


# Relevant Development Files

You should be able to use the "camera.py" and "vivetracker.py" file
directly in your python projects.


# Information

Additional information for developers and people interested in how the
VIVE Facial Tracker is accessed can be found in the file "dev_info"
