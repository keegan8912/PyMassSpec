"""
Class to model Intensity Matrix
"""

#############################################################################
#                                                                           #
#    PyMS software for processing of metabolomic mass-spectrometry data     #
#    Copyright (C) 2005-2012 Vladimir Likic                                 #
#    Copyright (C) 2019 Dominic Davis-Foster                                #
#                                                                           #
#    This program is free software; you can redistribute it and/or modify   #
#    it under the terms of the GNU General Public License version 2 as      #
#    published by the Free Software Foundation.                             #
#                                                                           #
#    This program is distributed in the hope that it will be useful,        #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of         #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          #
#    GNU General Public License for more details.                           #
#                                                                           #
#    You should have received a copy of the GNU General Public License      #
#    along with this program; if not, write to the Free Software            #
#    Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.              #
#                                                                           #
#############################################################################


import numpy
import math
import copy

from warnings import warn

import deprecation
from pyms import __version__

from pyms.Utils.Utils import is_str, is_list
from pyms.Utils.IO import open_for_writing, close_for_writing, save_data
from pyms.IonChromatogram import IonChromatogram
from pyms.MassSpectrum import MassSpectrum


try:
	import psyco
	psyco.full()
except ModuleNotFoundError:
	pass


class IntensityMatrix(object):
	"""
	:summary: Intensity matrix of binned raw data

	:author: Andrew Isaac
	:author: Dominic Davis-Foster (type assertions and properties)
	"""
	
	def __init__(self, time_list, mass_list, intensity_matrix):
		"""
		:summary: Initialize the IntensityMatrix data

		:param time_list: Retention time values
		:type time_list: list

		:param mass_list: Binned mass values
		:type mass_list: list

		:param intensity_matrix: Binned intensity values per scan
		:type intensity_matrix: list

		:author: Andrew Isaac
		"""
		
		# sanity check
		if not is_list(time_list) or not isinstance(time_list[0], (int, float)):
			raise TypeError("'time_list' must be a list of numbers")
		if not is_list(mass_list) or not isinstance(mass_list[0], (int, float)):
			raise TypeError("'mass_list' must be a list of numbers")
		if not is_list(intensity_matrix) \
				or not is_list(intensity_matrix[0]) \
				or not isinstance(intensity_matrix[0][0], (int, float)):
			raise TypeError("'intensity_matrix' must be a list, of a list, of numbers")
		if not len(time_list) == len(intensity_matrix):
			raise ValueError("'time_list' is not the same length as 'intensity_matrix'")
		if not len(mass_list) == len(intensity_matrix[0]):
			raise ValueError("'mass_list' is not the same size as 'intensity_matrix'")
		
		self.__time_list = time_list
		self.__mass_list = mass_list
		self.__intensity_matrix = intensity_matrix
		
		self.__min_rt = min(time_list)
		self.__max_rt = max(time_list)
		
		self.__min_mass = min(mass_list)
		self.__max_mass = max(mass_list)
		
		# Direct access for speed (DANGEROUS)
		#self.intensity_matrix = self.__intensity_matrix
		
		# Try to include parallelism.
		try:
			from mpi4py import MPI
			comm = MPI.COMM_WORLD
			num_ranks = comm.Get_size()
			rank = comm.Get_rank()
			M, N = len(intensity_matrix), len(intensity_matrix[0])
			lrr = (rank * M / num_ranks, (rank + 1) * M / num_ranks)
			lcr = (rank * N / num_ranks, (rank + 1) * N / num_ranks)
			m, n = (lrr[1] - lrr[0], lcr[1] - lcr[0])
			self.comm = comm
			self.num_ranks = num_ranks
			self.rank = rank
			self.M = M
			self.N = N
			self.local_row_range = lrr
			self.local_col_range = lcr
			self.m = m
			self.n = n
		
		# If we can't import mpi4py then continue in serial.
		except ModuleNotFoundError:
			pass
	
	def __len__(self):
		return len(self.time_list)
	
	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.time_list == other.time_list \
				   and self.mass_list == other.mass_list \
				   and self.intensity_matrix == other.intensity_matrix
		return NotImplemented
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.local_size' instead")
	def get_local_size(self):
		"""
		:summary: Gets the local size of intensity matrix.

		:return: Number of rows and cols
		:rtype: int

		:author: Luke Hodkinson
		"""
		
		return self.local_size
	
	@property
	def local_size(self):
		"""
		:summary: Gets the local size of intensity matrix.

		:return: Number of rows and cols
		:rtype: int

		:author: Luke Hodkinson
		"""
		
		# Check for parallel.
		if hasattr(self, 'comm'):
			return self.m, self.n
		
		# If serial call the regular routine.
		return self.size
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.size' instead")
	def get_size(self):
		"""
		:summary: Gets the size of intensity matrix

		:return: Number of rows and cols
		:rtype: int

		:author: Qiao Wang
		:author: Andrew Isaac
		:author: Luke Hodkinson
		:author: Vladimir Likic
		"""
		
		return self.size
	
	@property
	def size(self):
		"""
		:summary: Gets the size of intensity matrix

		:return: Number of rows and cols
		:rtype: int

		:author: Qiao Wang
		:author: Andrew Isaac
		:author: Luke Hodkinson
		:author: Vladimir Likic
		"""
		
		n_scan = len(self.__intensity_matrix)
		n_mz = len(self.__intensity_matrix[0])
		
		return n_scan, n_mz
	
	def iter_ms_indices(self):
		"""
		:summary: Iterates over local row indices

		:return: Current row index
		:rtype: int

		:author: Luke Hodkinson
		"""
		
		# Check for parallel.
		if hasattr(self, 'comm'):
			# At the moment we assume we break the matrix into contiguous
			# ranges. We've allowed for this to change by wrapping up the
			# iteration in this method.
			for i in range(self.local_row_range[0], self.local_row_range[1]):
				yield i
		
		else:
			# Iterate over global indices.
			n_scan = len(self.__intensity_matrix)
			for i in range(0, n_scan):
				yield i
	
	def iter_ic_indices(self):
		"""
		:summary: Iterate over local column indices

		:return: Current column index
		:rtype: int

		:author: Luke Hodkinson
		"""
		
		# Check for parallel.
		if hasattr(self, 'comm'):
			# At the moment we assume we break the matrix into contiguous
			# ranges. We've allowed for this to change by wrapping up the
			# iteration in this method.
			for i in range(self.local_col_range[0], self.local_col_range[1]):
				yield i
		
		else:
			# Iterate over global indices.
			n_mz = len(self.__intensity_matrix[0])
			for i in range(0, n_mz):
				yield i
	
	def set_ic_at_index(self, ix, ic):
		"""
		:summary: Sets the ion chromatogram specified by index to a new
			value

		:param ix: Index of an ion chromatogram in the intensity data
			matrix to be set
		:type ix: int
		:param ic: Ion chromatogram that will be copied at position 'ix'
			in the data matrix
		:type: IonChromatogram

		The length of the ion chromatogram must match the appropriate
		dimension of the intensity matrix.

		:author: Vladimir Likic
		"""
		
		if not isinstance(ix, (int, float)):
			raise TypeError("index not an integer")
		
		if not isinstance(ic, IonChromatogram):
			raise TypeError("'ic' must be an IonChromaogram object")
		
		# this returns an numpy.array object
		ia = ic.intensity_array
		
		# check if the dimension is ok
		if len(ia) != len(self.__intensity_matrix):
			raise ValueError("ion chromatogram incompatible with the intensity matrix")
		else:
			N = len(ia)
		
		# Convert 'ia' to a list. By convention, the attribute
		# __intensity_matrix of the class IntensityMatrix is a list
		# of lists. This makes pickling instances of IntensityMatrix
		# practically possible, since pickling numpy.array objects
		# produces ten times larger files compared to pickling python
		# lists.
		ial = ia.tolist()
		for i in range(N):
			self.__intensity_matrix[i][ix] = ial[i]
	
	def get_ic_at_index(self, ix):
		
		"""
		:summary: Returns the ion chromatogram at the specified index

		:param ix: Index of an ion chromatogram in the intensity data
			matrix
		:type ix: int

		:return: Ion chromatogram at given index
		:rtype: IonChromatogram

		:author: Qiao Wang
		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		if not isinstance(ix, (int, float)):
			raise TypeError("'ix must be a number")
		
		ia = []
		for i in range(len(self.__intensity_matrix)):
			ia.append(self.__intensity_matrix[i][ix])
		
		ic_ia = numpy.array(ia)
		mass = self.get_mass_at_index(ix)
		rt = copy.deepcopy(self.__time_list)
		
		return IonChromatogram(ic_ia, rt, mass)
	
	def get_ic_at_mass(self, mass=None):
		
		"""
		:summary: Returns the ion chromatogram for the specified mass.
			The nearest binned mass to mass is used.

			If no mass value is given, the function returns the total
			ion chromatogram.

		:param mass: Mass value of an ion chromatogram
		:type mass: int

		:return: Ion chromatogram for given mass
		:rtype: IonChromatogram

		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		if mass is None:
			return self.tic
		
		if mass < self.__min_mass or mass > self.__max_mass:
			print("min mass: ", self.__min_mass, "max mass:", self.__max_mass)
			raise IndexError("mass is out of range")
		
		ix = self.get_index_of_mass(mass)
		
		return self.get_ic_at_index(ix)
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.mass_list' instead")
	def get_mass_list(self):
		"""
		:summary: Returns a list of the binned masses

		:return: Binned mass list
		:rtype: list

		:author: Qiao Wang
		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		return self.mass_list
	
	@property
	def mass_list(self):
		"""
		:summary: Returns a list of the binned masses

		:return: Binned mass list
		:rtype: list

		:author: Qiao Wang
		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		return copy.deepcopy(self.__mass_list)
	
	@property
	def intensity_matrix(self):
		"""
		:summary: Returns a list of the binned masses

		:return: Binned mass list
		:rtype: list

		:author: Qiao Wang
		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		return self.__intensity_matrix
	
	def get_ms_at_index(self, ix):
		
		"""
		:summary: Returns a mass spectrum for a given scan index

		:param ix: The index of the scan
		:type ix: int

		:return: Mass spectrum
		:rtype: pyms.GCMS.Class.MassSpectrum

		:author: Andrew Isaac
		"""
		
		# TODO: should a deepcopy be returned?
		
		if not isinstance(ix, (int, float)):
			raise TypeError("'ix' must be an integer")
		
		scan = self.get_scan_at_index(ix)
		
		return MassSpectrum(self.__mass_list, scan)
	
	def get_scan_at_index(self, ix):
		
		"""
		:summary: Returns the spectral intensities for scan index

		:param ix: The index of the scan
		:type ix: int

		:return: Intensity values of scan spectra
		:rtype: list

		:author: Andrew Isaac
		"""
		
		if not isinstance(ix, (int, float)):
			raise TypeError("'ix' must be an integer")
		
		if ix < 0 or ix >= len(self.__intensity_matrix):
			raise IndexError("index out of range")
		
		return copy.deepcopy(self.__intensity_matrix[ix])
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.min_mass' instead")
	def get_min_mass(self):
		"""
		:summary: Returns the maximum binned mass

		:return: The maximum binned mass
		:rtype: float

		:author: Andrew Isaac
		"""
		
		return self.min_mass
	
	@property
	def min_mass(self):
		"""
		:summary: Returns the maximum binned mass

		:return: The maximum binned mass
		:rtype: float

		:author: Andrew Isaac
		"""
		
		return self.__min_mass
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.max_mass' instead")
	def get_max_mass(self):
		"""
		:summary: Returns the maximum binned mass

		:return: The maximum binned mass
		:rtype: float

		:author: Andrew Isaac
		"""
		
		return self.max_mass
	
	@property
	def max_mass(self):
		"""
		:summary: Returns the maximum binned mass

		:return: The maximum binned mass
		:rtype: float

		:author: Andrew Isaac
		"""
		
		return self.__max_mass
	
	def get_mass_at_index(self, ix):
		
		"""
		:summary: Returns binned mass at index

		:param ix: Index of binned mass
		:type ix: int

		:return: Binned mass
		:rtype: int

		:author: Andrew Isaac
		"""
		
		if not isinstance(ix, (int, float)):
			raise TypeError("'ix' must be an integer")
		
		if ix < 0 or ix >= len(self.__mass_list):
			raise IndexError("index out of range")
		
		return self.__mass_list[ix]
	
	def get_index_of_mass(self, mass):
		"""
		:summary: Returns the index of mass in the list of masses

		The nearest binned mass to given mass is used.

		:param mass: Mass to lookup in list of masses
		:type mass: float

		:return: Index of mass closest to given mass
		:rtype: int

		:author: Andrew Isaac
		"""
		
		best = self.__max_mass
		ix = 0
		for ii in range(len(self.__mass_list)):
			tmp = abs(self.__mass_list[ii] - mass)
			if tmp < best:
				best = tmp
				ix = ii
		return ix
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.matrix_list' instead")
	def get_matrix_list(self):
		
		"""
		:summary: Returns a copy of the intensity matrix as a
			list of lists of floats

		:return: Matrix of intensity values
		:rtype: list

		:author: Andrew Isaac
		"""
		
		return self.matrix_list
	
	@property
	def matrix_list(self):
		"""
		:summary: Returns a copy of the intensity matrix as a
			list of lists of floats

		:return: Matrix of intensity values
		:rtype: list

		:author: Andrew Isaac
		"""
		
		return copy.deepcopy(self.__intensity_matrix)
	
	@deprecation.deprecated(deprecated_in="2.1.2", removed_in="2.2.0",
							current_version=__version__,
							details="Use 'IntensityMatrix.time_list' instead")
	def get_time_list(self):
		"""
		:summary: Returns a copy of the time list

		:return: List of retention times
		:rtype: list

		:author: Andrew Isaac
		"""
		
		return self.time_list
	
	@property
	def time_list(self):
		"""
		:summary: Returns a copy of the time list

		:return: List of retention times
		:rtype: list

		:author: Andrew Isaac
		"""
		
		return copy.deepcopy(self.__time_list)
	
	def get_index_at_time(self, time):
		
		"""
		:summary: Returns the nearest index corresponding to the given time

		:param time: Time in seconds
		:type time: float

		:return: Nearest index corresponding to given time
		:rtype: int

		:author: Lewis Lee
		:author: Tim Erwin
		:author: Vladimir Likic
		"""
		
		if not isinstance(time, (int, float)):
			raise TypeError("'time' must be a number")
		
		if time < min(self.__time_list) or time > max(self.__time_list):
			raise IndexError("time %.2f is out of bounds (min: %.2f, max: %.2f)" %
							 (time, self.__min_rt, self.__max_rt))
		
		time_list = self.__time_list
		time_diff_min = max(self.__time_list)
		ix_match = None
		
		for ix in range(len(time_list)):
			
			time_diff = math.fabs(time - time_list[ix])
			
			if time_diff < time_diff_min:
				ix_match = ix
				time_diff_min = time_diff
		
		return ix_match
	
	def crop_mass(self, mass_min, mass_max):
		
		"""
		:summary: Crops mass spectrum

		:param mass_min: Minimum mass value
		:type mass_min: int or float
		:param mass_max: Maximum mass value
		:type mass_max: int or float

		:return: none
		:rtype: NoneType

		:author: Andrew Isaac
		"""
		
		if not isinstance(mass_min, (int, float)) or not isinstance(mass_max, (int, float)):
			raise TypeError("'mass_min' and 'mass_max' must be numbers")
		if mass_min >= mass_max:
			raise ValueError("'mass_min' must be less than 'mass_max'")
		if mass_min < self.__min_mass:
			raise ValueError("'mass_min' is less than the smallest mass: %.3f" %
							 self.__min_mass)
		if mass_max > self.__max_mass:
			raise ValueError("'mass_max' is greater than the largest mass: %.3f" %
							 self.__max_mass)
		
		# pre build mass_list and list of indecies
		mass_list = self.__mass_list
		new_mass_list = []
		ii_list = []
		for ii in range(len(mass_list)):
			mass = mass_list[ii]
			if mass >= mass_min and mass <= mass_max:
				new_mass_list.append(mass)
				ii_list.append(ii)
		
		# update intensity matrix
		im = self.__intensity_matrix
		for spec_jj in range(len(im)):
			new_spec = []
			for ii in ii_list:
				new_spec.append(im[spec_jj][ii])
			im[spec_jj] = new_spec
		
		self.__mass_list = new_mass_list
		self.__min_mass = min(new_mass_list)
		self.__max_mass = max(new_mass_list)
	
	def null_mass(self, mass):
		
		"""
		:summary: Ignore given (closest) mass in spectra

		:param mass: Mass value to remove
		:type mass: int or float

		:author: Andrew Isaac
		"""
		
		if not isinstance(mass, (int, float)):
			raise TypeError("'mass' must be numbers")
		if mass < self.__min_mass or mass > self.__max_mass:
			raise IndexError("'mass' not in mass range: %.3f to %.3f" % (self.__min_mass, \
																		 self.__max_mass))
		
		ii = self.get_index_of_mass(mass)
		
		im = self.__intensity_matrix
		for spec_jj in range(len(im)):
			im[spec_jj][ii] = 0
	
	def reduce_mass_spectra(self, N=5):
		
		"""
		:summary: Reduces mass spectra by retaining top N
			intensities, discarding all other intensities.

		:param N: The number of top intensities to keep
		:type N: int

		:author: Vladimir Likic
		"""
		
		if not isinstance(N, (int, float)):
			raise TypeError("'N' must be a number")
		
		# loop over all mass spectral scans
		for ii in range(len(self.__intensity_matrix)):
			
			# get the next mass spectrum as list of intensities
			intensity_list = self.__intensity_matrix[ii]
			n = len(intensity_list)
			
			# get the indices of top N intensities
			top_indices = list(range(n))
			top_indices.sort(key=lambda i: intensity_list[i], reverse=True)
			top_indices = top_indices[:N]
			
			# initiate new mass spectrum, and retain only top N intensities
			intensity_list_new = []
			
			for jj in range(n):
				intensity_list_new.append(0.0)
				if jj in top_indices:
					intensity_list_new[jj] = intensity_list[jj]
			
			self.__intensity_matrix[ii] = intensity_list_new
	
	def export_ascii(self, root_name, format='dat'):
		"""
		:summary: Exports the intensity matrix, retention time vector, and
			m/z vector to the ascii format

			By default, export_ascii("NAME") will create NAME.im.dat, NAME.rt.dat,
			and NAME.mz.dat where these are the intensity matrix, retention
			time vector, and m/z vector in tab delimited format. If format='csv',
			the files will be in the CSV format, named NAME.im.csv, NAME.rt.csv,
			and NAME.mz.csv.

		:param root_name: Root name for the output files
		:type root_name: str
		:param format:
		:type format: str


		:return: none
		:rtype: NoneType

		:author: Milica Ng
		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		if not is_str(root_name):
			raise TypeError("'root_name' must be a string")
		
		if format == 'dat':
			separator = " "
			extension = ".dat"
		elif format == 'csv':
			separator = ","
			extension = ".csv"
		else:
			raise ValueError(f"Unknown format '{format}'. Only 'dat' and 'csv' supported")
		
		# export 2D matrix of intensities
		vals = self.__intensity_matrix
		save_data(root_name + '.im' + extension, vals, sep=separator)
		
		# export 1D vector of m/z's, corresponding to rows of
		# the intensity matrix
		mass_list = self.__mass_list
		save_data(root_name + '.mz' + extension, mass_list, sep=separator)
		
		# export 1D vector of retention times, corresponding to
		# columns of the intensity matrix
		time_list = self.__time_list
		save_data(root_name + '.rt' + extension, time_list, sep=separator)
	
	def export_leco_csv(self, file_name):
		"""
		:summary: Exports data in LECO CSV format

		:param file_name: File name
		:type file_name: str

		:author: Andrew Isaac
		:author: Vladimir Likic
		"""
		
		if not is_str(file_name):
			raise TypeError("'file_name' must be a string")
		
		mass_list = self.__mass_list
		time_list = self.__time_list
		vals = self.__intensity_matrix
		
		fp = open_for_writing(file_name)
		
		# Format is text header with:
		# "Scan","Time",...
		# and the rest is "TIC" or m/z as text, i.e. "50","51"...
		# The following lines are:
		# scan_number,time,value,value,...
		# scan_number is an int, rest seem to be fixed format floats.
		# The format is 0.000000e+000
		
		# write header
		fp.write("\"Scan\",\"Time\"")
		for ii in mass_list:
			if isinstance(ii, (int, float)):
				fp.write(",\"%d\"" % int(ii))
			else:
				raise TypeError("mass list datum not a number")
		fp.write("\r\n")  # windows CR/LF
		
		# write lines
		for ii in range(len(time_list)):
			fp.write("%s,%#.6e" % (ii, time_list[ii]))
			for jj in range(len(vals[ii])):
				if isinstance(vals[ii][jj], (int, float)):
					fp.write(",%#.6e" % (vals[ii][jj]))
				else:
					raise TypeError("datum not a number")
			fp.write("\r\n")
		
		close_for_writing(fp)
	
	
def import_leco_csv(file_name):
	"""
	:summary: Imports data in LECO CSV format

	:param file_name: File name
	:type file_name: str

	:return: Data as an IntensityMatrix
	:rtype: pyms.GCMS.Class.IntensityMatrix

	:author: Andrew Isaac
	"""
	
	if not is_str(file_name):
		raise TypeError("'file_name' not a string")
	
	lines_list = open(file_name, 'r')
	data = []
	time_list = []
	mass_list = []
	
	# Format is text header with:
	# "Scan","Time",...
	# and the rest is "TIC" or m/z as text, i.e. "50","51"...
	# The following lines are:
	# scan_number,time,value,value,...
	# scan_number is an int, rest seem to be fixed format floats.
	# The format is 0.000000e+000
	
	num_mass = 0
	FIRST = True
	HEADER = True
	data_col = -1
	time_col = -1
	# get each line
	for line in lines_list:
		cols = -1
		data_row = []
		if len(line.strip()) > 0:
			data_list = line.strip().split(',')
			# get each value in line
			for item in data_list:
				item = item.strip()
				item = item.strip('\'"')  # remove quotes (in header)
				
				# Get header
				if HEADER:
					cols += 1
					if len(item) > 0:
						if item.lower().find("time") > -1:
							time_col = cols
						try:
							value = float(item)
							# find 1st col with number as header
							if FIRST and value > 1:  # assume >1 mass
								data_col = cols
								# assume time col is previous col
								if time_col < 0:
									time_col = cols - 1
								FIRST = False
							mass_list.append(value)
							num_mass += 1
						except ValueError:
							pass
				# Get rest
				else:
					cols += 1
					if len(item) > 0:
						try:
							value = float(item)
							if cols == time_col:
								time_list.append(value)
							elif cols >= data_col:
								data_row.append(value)
						except ValueError:
							pass
			
			# check row length
			if not HEADER:
				if len(data_row) == num_mass:
					data.append(data_row)
				else:
					warn("ignoring row")
			
			HEADER = False
	
	# check col lengths
	if len(time_list) != len(data):
		warn("number of data rows and time list length differ")
	
	return IntensityMatrix(time_list, mass_list, data)

def build_intensity_matrix(data, bin_interval=1, bin_left=0.5, bin_right=0.5, min_mass=None):
	"""
	:summary: Sets the full intensity matrix with flexible bins

	:param data: Raw GCMS data
	:type data: pyms.GCMS.Class.GCMS_data

	:param bin_interval: interval between bin centres (default 1)
	:type bin_interval: IntType or float

	:param bin_left: left bin boundary offset (default 0.5)
	:type bin_left: float

	:param bin_right: right bin boundary offset (default 0.5)
	:type bin_right: float

	:param min_mass: Minimum mass to bin (default minimum mass from data)
	:type min_mass: bool

	:return: Binned IntensityMatrix object
	:rtype: pyms.GCMS.Class.IntensityMatrix

	:author: Qiao Wang
	:author: Andrew Isaac
	:author: Vladimir Likic
	"""
	
	from pyms.GCMS.Class import GCMS_data
	
	if not isinstance(data, GCMS_data):
		raise TypeError("'data' must be a GCMS_data object")
	if bin_interval <= 0:
		raise ValueError("The bin interval must be larger than zero.")
	if not isinstance(bin_left, (int, float)):
		raise TypeError("'bin_left' must be a number.")
	if not isinstance(bin_right, (int, float)):
		raise TypeError("'bin_right' must be a number.")
	
	if not min_mass:
		min_mass = data.min_mass
	max_mass = data.max_mass
	
	return __fill_bins(data, min_mass, max_mass, bin_interval, bin_left, bin_right)


def build_intensity_matrix_i(data, bin_left=0.3, bin_right=0.7):
	"""
	:summary: Sets the full intensity matrix with integer bins

	:param data: Raw GCMS data
	:type data: pyms.GCMS.Class.GCMS_data

	:param bin_left: left bin boundary offset (default 0.3)
	:type bin_left: float

	:param bin_right: right bin boundary offset (default 0.7)
	:type bin_right: float

	:return: Binned IntensityMatrix object
	:rtype: pyms.GCMS.Class.IntensityMatrix

	:author: Qiao Wang
	:author: Andrew Isaac
	:author: Vladimir Likic
	"""
	
	from pyms.GCMS.Class import GCMS_data
	
	if not isinstance(data, GCMS_data):
		raise TypeError("'data' must be a GCMS_data object")
	if not isinstance(bin_left, (int, float)):
		raise TypeError("'bin_left' must be a number.")
	if not isinstance(bin_right, (int, float)):
		raise TypeError("'bin_right' must be a number.")
	
	min_mass = data.min_mass
	max_mass = data.max_mass
	
	# Calculate integer min mass based on right boundary
	bin_right = abs(bin_right)
	min_mass = int(min_mass + 1 - bin_right)
	
	return __fill_bins(data, min_mass, max_mass, 1, bin_left, bin_right)


def __fill_bins(data, min_mass, max_mass, bin_interval, bin_left, bin_right):
	"""
	:summary: Fills the intensity values for all bins

	:param data: Raw GCMS data
	:type data: pyms.GCMS.Class.GCMS_data
	:param min_mass: minimum mass value
	:type min_mass: IntType or float
	:param max_mass: maximum mass value
	:type max_mass: IntType or float
	:param bin_interval: interval between bin centres
	:type bin_interval: IntType or float
	:param bin_left: left bin boundary offset
	:type bin_left: float
	:param bin_right: right bin boundary offset
	:type bin_right: float

	:return: Binned IntensityMatrix object
	:rtype: pyms.GCMS.Class.IntensityMatrix

	:author: Qiao Wang
	:author: Andrew Isaac
	:author: Moshe Olshansky
	:author: Vladimir Likic
	"""

	if not (abs(bin_left+bin_right-bin_interval) < 1.0e-6*bin_interval):
		raise ValueError("there should be no gaps or overlap.")

	bin_left = abs(bin_left)
	bin_right = abs(bin_right)

	# To convert to int range, ensure bounds are < 1
	bl = bin_left - int(bin_left)

	# Number of bins
	num_bins = int(float(max_mass+bl-min_mass)/bin_interval)+1

	# initialise masses to bin centres
	mass_list = [i * bin_interval + min_mass for i in range(num_bins)]

	# Modified binning loops. I've replaced the deepcopy getting routines with
	# the alias properties. This way we can avoid performing the copies when
	# it is clear that we do not intend on modifying the contents of the arrays
	# here.
	#           - Luke Hodkinson, 18/05/2010

	# fill the bins
	intensity_matrix = []
	for scan in data.scan_list: # use the alias, not the copy (Luke)
		intensity_list = [0.0] * num_bins
		masses = scan.mass_list # use the alias, not the copy (Luke)
		intensities = scan.intensity_list # use the alias, not the copy (Luke)
		for ii in range(len(masses)):
			mm = int((masses[ii] + bl - min_mass)/bin_interval)
			intensity_list[mm] += intensities[ii]
		intensity_matrix.append(intensity_list)

	return IntensityMatrix(data.time_list, mass_list, intensity_matrix)


def __fill_bins_old(data, min_mass, max_mass, bin_interval, bin_left, bin_right):
	"""
	:summary: Fills the intensity values for all bins

	:param data: Raw GCMS data
	:type data: pyms.GCMS.Class.GCMS_data
	:param min_mass: minimum mass value
	:type min_mass: IntType or float
	:param max_mass: maximum mass value
	:type max_mass: IntType or float
	:param bin_interval: interval between bin centres
	:type bin_interval: IntType or float
	:param bin_left: left bin boundary offset
	:type bin_left: float
	:param bin_right: right bin boundary offset
	:type bin_right: float

	:return: Binned IntensityMatrix object
	:rtype: pyms.GCMS.Class.IntensityMatrix

	:author: Qiao Wang
	:author: Andrew Isaac
	:author: Vladimir Likic
	"""
	
	bin_left = abs(bin_left)
	bin_right = abs(bin_right)

	# To convert to int range, ensure bounds are < 1
	bl = bin_left - int(bin_left)

	# Number of bins
	num_bins = int(float(max_mass+bl-min_mass)/bin_interval)+1

	# initialise masses to bin centres
	mass_list = [i * bin_interval + min_mass for i in range(num_bins)]

	# fill the bins
	intensity_matrix = []
	for scan in data.get_scan_list():
		intensity_list = [0.0] * num_bins
		masses = scan.get_mass_list()
		intensities = scan.get_intensity_list()
		for mm in range(num_bins):
			for ii in range(len(scan)):
				if masses[ii] >= mass_list[mm]-bin_left and masses[ii] < mass_list[mm]+bin_right:
					intensity_list[mm] += intensities[ii]
		intensity_matrix.append(intensity_list)

	return IntensityMatrix(data.get_time_list(), mass_list, intensity_matrix)
