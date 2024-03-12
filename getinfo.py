#(c) 2024  David Shadoff
import os
import sys
import time

# Notes:
#
# This program will write the PC-FX's external Backup memory card (FX-BMP) from a 128KB file
#
#   Usage: getinfo <input_file>
#
#   Example:
#     python getinfo.py pcfxbmp.bin
#

FAT_12 = 1
FAT_16 = 2

INTERNAL_MEMORY = 1
EXTERNAL_MEMORY = 2
NON_PCFX_MEMORY = 3

DIR_ENTRY_SIZE = 0x20

def get_memory_type(b_array):
    oemname = b_array[3:11].decode('utf-8')
    if (oemname == "PCFXSram"):
        type = INTERNAL_MEMORY
    elif (oemname == "PCFXCard"):
        type = EXTERNAL_MEMORY
    else:
        type = NON_PCFX_MEMORY
    return type

def get_8bit(b_array, offset):
    num = int(b_array[offset])
    return num

def get_16bit(b_array, offset):
    num = int(b_array[offset]) + (256 * int(b_array[offset+1]))
    return num

def get_32bit(b_array, offset):
    num = int(b_array[offset]) + (int(b_array[offset+1])<<8) + (int(b_array[offset+2])<<16) + (int(b_array[offset+3])<<24)
    return num

def size_in_sectors(size, sector_size):
    temp = int(size / sector_size)
    if (temp != (size/sector_size) ):
        sectors = temp + 1
    else:
        sectors = temp
    return sectors

def fat_entry(b_array, start_of_fat, fs_type, entry_num):
    if (fs_type == FAT_16):
        offset = start_of_fat + (entry_num * 2)
        low = int(b_array[offset])
        high = (int(b_array[offset+1]) << 8 )
        fat_entry = high + low
    else:
        if (entry_num & 1):
            offset = start_of_fat + int(entry_num / 2) * 3
            low = (int(b_array[offset+1]) & 0xF0) >> 4
            high = (int(b_array[offset+2]) << 4 )
            fat_entry = high + low
        else:
            offset = start_of_fat + int(entry_num / 2) * 3
            low = int(b_array[offset])
            high = (int(b_array[offset+1]) & 0x0F) << 8 
            fat_entry = high + low
    return fat_entry

def free_fat_entries(b_array, start_of_fat, fs_type, fat_entries):
    free_count = 0
    i = 0
    while (i < fat_entries):
        if (fat_entry(b_array, start_of_fat, fs_type, i) == 0):
            free_count = free_count + 1
        i = i + 1
    return free_count

def get_next_cluster(b_array, start_of_fat, fs_type, cluster):
    if (cluster < 0):
        next_cluster = cluster + 1
    else:
        next_cluster = fat_entry(b_array, start_of_fat, fs_type, cluster)
    return next_cluster

def get_direntry_inuse(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    return int(dir_array[base])

def get_direntry_attr(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    return int(dir_array[base + 0x0B])

def get_direntry_ext(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    ext_sjis = dir_array[(base + 0x08):(base + 0x0B)].decode('cp932')
    while (ext_sjis[-1] == '\x00'):
        ext_sjis = ext_sjis[:-1]
    ext = ext_sjis.rstrip()
    return ext

def get_direntry_fname(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    fname_barray = dir_array[base:(base+8)] + dir_array[(base+0x0C):(base+0x16)]
    fname_sjis = fname_barray.decode('cp932')
    while (fname_sjis[-1] == '\x00'):
        fname_sjis = fname_sjis[:-1]
    fname = fname_sjis.rstrip()
    ext = get_direntry_ext(dir_array, entry)
    if (ext != ""):
        fname = fname + "." + ext
    return fname

def get_direntry_date(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    dir_date = get_16bit(dir_array, base + 0x18)
    return dir_date

def get_direntry_time(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    dir_time = get_16bit(dir_array, base + 0x16)
    return dir_time

def get_direntry_firstcluster(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    dir_firstcluster = get_16bit(dir_array, base + 0x1A)
    return dir_firstcluster

def get_direntry_filesize(dir_array, entry):
    base = (entry * DIR_ENTRY_SIZE)
    dir_filesize = get_32bit(dir_array, base + 0x1C)
    return dir_filesize


# Yes, I think it's silly to duplicate code for Root dir and subdir but
# handling arrays of arrays seems to be more difficult than necessary in
# Python and in any case, PC-FX seems to only have subdirectories in root,
# and only files in subdirectories... so one level of near-duplication
# can be considered acceptable in this case
#
def execute_subdir(path, b_array, dir_array):
    s_dirarray_size = int(len(dir_array)/DIR_ENTRY_SIZE)
    s_entrynum = 0
    count_dir = 0
    count_files = 0
    while (s_entrynum < s_dirarray_size):
        s_inuse = get_direntry_inuse(dir_array, s_entrynum)
        if (s_inuse == 0xE5):
            s_entrynum = s_entrynum + 1
            continue
        elif (s_inuse == 0):
            break

        s_fname = get_direntry_fname(dir_array, s_entrynum)
        if (s_fname == "."):
#            print("Pointer to current dir")
            s_entrynum = s_entrynum + 1
            continue
        if (s_fname == ".."):
#            print("Pointer to parent dir")
            s_entrynum = s_entrynum + 1
            continue

        s_attr = get_direntry_attr(dir_array, s_entrynum)
        if (s_attr == 0x10):
            s_entrytype = "D"
        else:
            s_entrytype = "F"

        s_f_ext = get_direntry_ext(dir_array, s_entrynum)
        s_filesize = get_direntry_filesize(dir_array, s_entrynum)
        s_f_date = get_direntry_date(dir_array, s_entrynum)
        s_f_time = get_direntry_time(dir_array, s_entrynum)

        s_firstcluster = get_direntry_firstcluster(dir_array, s_entrynum)
        s_firstbyte = start_of_data+((s_firstcluster-2)*sector_size)
        s_numclusters = 1

        if (s_entrytype == "D"):     #  Directory:
            count_dir = count_dir + 1
            print("second level directory - shouldn't happen")
            s_subdir = memory[s_firstbyte:(s_firstbyte+sector_size)]
            s_nextcluster = get_next_cluster(b_array, start_of_fat, fs_type, s_firstcluster)
            while (s_nextcluster != 0xFFF):
                s_numclusters = s_numclusters + 1
                s_firstbyte = start_of_data+((s_nextcluster-2)*sector_size)
                s_subdir = s_subdir + memory[s_firstbyte:(s_firstbyte+sector_size)]
                s_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, s_nextcluster)
            print("DIR:  ", s_entrynum, ",", s_entrytype, ",",  s_fname, ",", s_f_ext, ",", s_filesize, ",", s_f_date, ",", s_f_time)
            # Not implemented, as this is never expected
#            createpath = os.path.join(fname)
#            print(createpath)
#            os.mkdir(createpath)
        # Process directory as above

        elif (s_entrytype == "F"):   # File - although these aren't expected in the root directory
            count_files = count_files + 1
            s_file = memory[s_firstbyte:(s_firstbyte+sector_size)]
            s_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, s_firstcluster)
            while (s_nextcluster != 0xFFF):
                s_numclusters = s_numclusters + 1
                s_firstbyte = start_of_data+((s_nextcluster-2)*sector_size)
                s_file = s_file + memory[s_firstbyte:(s_firstbyte+sector_size)]
                s_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, s_nextcluster)
            print("   {:19}  ".format(s_fname), "{:10,}".format(s_filesize))
        # Create and save file
        s_createpath = os.path.join(path, s_fname)
        f_new = open(s_createpath, 'wb')
        f_new.write(s_file[0:s_filesize])
        f_new.close()

        s_entrynum = s_entrynum + 1

    return count_files
        
####################
# Start of execution
####################
if ((len(sys.argv) != 2)):
    print("Usage: getinfo <input_file>")
    exit()


# Check that the file is exactly 128KB in size:
#
# file_stat = os.stat(sys.argv[1])
# if (file_stat.st_size != 131072):
#     print("File must be 131072 bytes in size")
#     exit()
# 

f = open(sys.argv[1], 'rb') 

memory = f.read()
databytes=bytearray(memory)

#
# Gather basic information about the filesystem:
#
memory_type = get_memory_type(memory)
if (memory_type == NON_PCFX_MEMORY):
    print("Not a PCFX memory save file")
    exit()
elif (memory_type == INTERNAL_MEMORY):
    print("INTERNAL SAVE FILE")
elif (memory_type == EXTERNAL_MEMORY):
    print("EXTERNAL SAVE FILE")


sector_size = get_16bit(memory, 0x0B)
sectors_per_cluster = get_16bit(memory, 0x0D)
reserved_sectors = get_16bit(memory, 0x0E)
total_sectors = get_16bit(memory, 0x13)
fat_sectors = get_16bit(memory, 0x16)
max_root_dir_entries = get_16bit(memory, 0x11)
root_dir_size = max_root_dir_entries * DIR_ENTRY_SIZE 
root_dir_sectors = size_in_sectors(root_dir_size, sector_size)

start_of_fat = reserved_sectors * sector_size
start_of_root_dir = (reserved_sectors + fat_sectors) * sector_size
start_of_data = (reserved_sectors + fat_sectors + root_dir_sectors) * sector_size

data_sectors = (total_sectors - reserved_sectors - fat_sectors - root_dir_sectors)
if (data_sectors > 0xFFF):
    fs_type = FAT_16
    fs_type_string = "FAT16"
else:
    fs_type = FAT_12
    fs_type_string = "FAT12"


media_size = sector_size * total_sectors
media_size_kb = int(media_size / 1024)
free_sectors = free_fat_entries(memory, start_of_fat, fs_type, data_sectors)

# Base information (should be optional):
#
print("Sector Size:          {0}".format(sector_size))
print("Total Sectors:        {0}".format(total_sectors))
print("Reserved Sectors:     {0}".format(reserved_sectors))
print("FAT Sectors:          {0}".format(fat_sectors))
print("Root Dir Sectors:     {0}".format(root_dir_sectors))
print("Data Sectors:         {0}".format(data_sectors))
print("Filesystem type:      {0}".format(fs_type_string))
print("Free Sectors:         {0}".format(free_sectors))

print(" ")

# User-level information:
#
print("Media Size (KB):      {0:>4}".format(media_size_kb))
print("Usable Space (KB):    {0:>8.3f}".format( round( (sector_size * data_sectors/1024), 3) ))
print("Free Space (KB):      {0:>8.3f}".format( round( (sector_size * free_sectors/1024), 3) ))

print(" ")

# Now, traverse root directory:
dirstart = start_of_root_dir
r_entrynum = 0
indent = "  "
startcluster = 0 - root_dir_sectors
rootdir = memory[start_of_root_dir:(start_of_root_dir + (root_dir_sectors * sector_size)) ]

print("start_of_data = ",start_of_data)

while (True):
    r_inuse = get_direntry_inuse(rootdir, r_entrynum)
    if (r_inuse == 0xE5):
        r_entrynum = r_entrynum + 1
        continue
    elif (r_inuse == 0):
        break

    r_fname = get_direntry_fname(rootdir, r_entrynum)
    if (r_fname == "."):
        print("Pointer to current dir")
        r_entrynum = r_entrynum + 1
        continue
    if (r_fname == ".."):
        print("Pointer to parent dir")
        r_entrynum = r_entrynum + 1
        continue

    print(" ")

    r_attr = get_direntry_attr(rootdir, r_entrynum)
    if (r_attr == 0x10):
        r_entrytype = "D"
    else:
        r_entrytype = "F"

    r_f_ext = get_direntry_ext(rootdir, r_entrynum)
    r_filesize = get_direntry_filesize(rootdir, r_entrynum)
    r_f_date = get_direntry_date(rootdir, r_entrynum)
    r_f_time = get_direntry_time(rootdir, r_entrynum)

    r_firstcluster = get_direntry_firstcluster(rootdir, r_entrynum)
    r_firstbyte = start_of_data+((r_firstcluster-2)*sector_size)
    r_numclusters = 1

    if (r_entrytype == "D"):     #  Directory:
        r_subdir = memory[r_firstbyte:(r_firstbyte+sector_size)]
        r_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, r_firstcluster)
        while (r_nextcluster != 0xFFF):
            r_numclusters = r_numclusters + 1
            r_firstbyte = start_of_data+((r_nextcluster-2)*sector_size)
            r_subdir = r_subdir + memory[r_firstbyte:(r_firstbyte+sector_size)]
            r_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, r_nextcluster)
        r_createpath = os.path.join(r_fname)
        print("{:19}           <DIR>".format(r_fname))
        os.mkdir(r_createpath)
        execute_subdir(r_createpath, memory, r_subdir)
        # Process directory as above

    elif (r_entrytype == "F"):   # File - although these aren't expected in the root directory
        print("top level file - shouldn't happen")
        r_file = memory[r_firstbyte:(r_firstbyte+sector_size)]
        r_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, r_firstcluster)
        while (r_nextcluster != 0xFFF):
            r_numclusters = r_numclusters + 1
            r_firstbyte = start_of_data+((r_nextcluster-2)*sector_size)
            r_file = r_file + memory[r_firstbyte:(r_firstbyte+sector_size)]
            r_nextcluster = get_next_cluster(memory, start_of_fat, fs_type, r_nextcluster)
        print(indent, "FILE: ", r_entrynum, ",", r_entrytype, ",",  r_fname, ",", r_f_ext, ",", r_filesize, ",", r_f_date, ",", r_f_time)
        # Create and save file - not implemented, since this is not expected !!

    r_entrynum = r_entrynum + 1


f.close()

