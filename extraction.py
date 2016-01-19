import scipy as sp
import numpy as np
import numpy.linalg as la
import scipy.linalg as sla
import matplotlib.pyplot as pl
import skrf as rf # RF functions. To install this do "conda install -c scikit-rf  scikit-rf" from the command line if you have Anaconda Python installed, otherwise do "pip install scikit-rf"
import math
import glob
import argparse


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("pad_L_s2p_file", help="Filename for L structure measurement to be used for pad extraction")
	parser.add_argument("pad_2L_s2p_file", help="Filename for 2L structure measurement to be used for pad extraction")
	parser.add_argument("--struct_s2p_name", default="*.s2p", help="Filename for structure to convert. If this argument is presented, ONLY file names conforming to this naming scheme will be processed. Accepts globs (i.e. input *_foo.s2p to process all files ending with _foo.s2p). Default is *.s2p (all s2p files)")
	parser.add_argument("--skip_deembed", default=False, action='store_true', help="Use this flag to skip pad deembedding. You will still need to input the pad L/2L filenames, but they will not be used")	
	parser.add_argument("--z0_real", type=float, default=50, help="Real portion of probe impedance. Default is 50 Ohms")
	parser.add_argument("--z0_imag", type=float, default=0, help="Imaginary portion of probe impedance. Default is 0 Ohms (Default impedance is 50 + 0j)")
	parser.add_argument("--skip_plots", action="store_true", default=False, help="Skip plotting for faster data extraction")
	parser.add_argument("--method", default="distributed", choices=["distributed", "lumped", "distributed_abcd", "distributed_sri"], help="Type of RLGC extraction to perform. distributed (default) -- treats structure as transmission line and extracts from S in DB/DEG form. lumped -- treats structure as lumped element. distributed_abcd -- extracts from ABCD matrices. distributed_sri -- extracts from S in REAL/IMAG format.") 
	args = parser.parse_args()
	
	z0_probe = complex(args.z0_real, args.z0_imag)
	print("NOTE: Ignore the above warning about pyvisa (if any). It is unimportant for our purposes.\n")
	
	(freq_mat, R_mat, L_mat, G_mat, C_mat) = extract_rlgc(args.pad_L_s2p_file, args.pad_2L_s2p_file, z0_probe, args.method, args.skip_plots, args.struct_s2p_name)
	
	
	

def extract_rlgc(pad_L_s2p_filename, pad_2L_s2p_filename, z0_probe=50.0, method="distributed", skip_plots=False, struct_s2p_name="*.s2p"):

	file_list = glob.glob(struct_s2p_name)
	
	print("Pad Deembedding file (L):  {0:s}".format(pad_L_s2p_filename) )
	print("Pad Deembedding file (2L): {0:s}".format(pad_2L_s2p_filename) )
	# Get pad deembedding parameters
	(freq, abcd_pad, abcd_pad_inv, Sri_pad, Sdb_pad, Sdeg_pad, net_pad) = get_pad_abcd(pad_L_s2p_filename, pad_2L_s2p_filename, z0_probe)
	
	print("Extracting RLGC using {0:s} method...".format(method))
	freq_mat = []
	R_mat = []
	L_mat = []
	G_mat = []
	C_mat = []
	length_vec = []
	width_vec = []
	name_vec = []
	for filename in file_list:
		# First strip out any stuff from the path
		nfilename_arr = filename.split("\\")
		nfilename = nfilename_arr[-1]
		
		# now process the actual filename
		filename_arr = nfilename.split("_")
		trace_length_um = int(filename_arr[0])
		length_m = trace_length_um * 1e-6
		
		trace_width_name = filename_arr[1]
		trace_width_um = int( trace_width_name[0:-2] ) # get rid of the "um" in the width section
		data_final_arr = filename_arr[-1].split(".")
		data_final_str = data_final_arr[0]
		print("\tL: {0:d}um \t W: {1:d}um \t Sample: {2:s}".format(trace_length_um, trace_width_um, data_final_str) )
		
		# Construct output filename for each input file
		# Requires input files to be named as follows
		# $LENGTH_$WIDTHum_$WHATEVER.s2p
		# where $LENGTH is the structure length in microns
		# $WIDTH is the structure width in microns
		# and $WHATEVER is whatever's left over,  typically a sample number and maybe some other info
		structure_string = "L{0:d}um_W{1:d}um_{2:s}".format(trace_length_um, trace_width_um, data_final_str)
		rlgc_filename = "rlgc_" + structure_string + ".csv"
		structure_L_s2p_filename = filename
		
		net_dut = rf.Network(structure_L_s2p_filename, z0_probe)
		Sdb_dut = net_dut.s_db
		Sdeg_dut = net_dut.s_deg
		abcd_dut = sdb2abcd(Sdb_dut, Sdeg_dut)
		
		(freq, R, L, G, C) = extract_rlcg_from_measurement( freq, length_m, abcd_pad_inv, abcd_dut, z0_probe, method)
		freq_mat.append(freq)
		R_mat.append(R)
		L_mat.append(L)
		G_mat.append(G)
		C_mat.append(C)
		name_vec.append(structure_string)
		length_vec.append(trace_length_um)
		width_vec.append(trace_width_um)


		write_rlgc(freq, R, L, G, C, rlgc_filename)
		
		if not skip_plots:
			plot_rlgc(freq, R, L, G, C, structure_string)
			plot_s_params(freq, Sdb_dut, Sdeg_dut, structure_string)
	
	write_data(freq_mat[0], R_mat, name_vec, "R.csv")
	write_data(freq_mat[0], L_mat, name_vec, "L.csv")
	write_data(freq_mat[0], C_mat, name_vec, "G.csv")
	write_data(freq_mat[0], G_mat, name_vec, "C.csv")
			
	return (freq_mat, R_mat, L_mat, G_mat, C_mat, name_vec, length_vec, width_vec)


def write_data( freq, data_mat, name_mat, filename):
	outfile = open(filename, 'w')
	
	data_shape = np.shape(data_mat)
	num_freqs = data_shape[0]
	num_cols = data_shape[1]
	outstr = ",".join(name_mat)
	outfile.write("{0:s},{1:s}\n".format("Freq (Hz)", outstr) )
	
	data_mat = np.array(data_mat)

	for idx, f in enumerate(freq):
		data_str_vec = [ "{0:.8g}".format(el) for el in data_mat[:,idx] ]
		data_str = ",".join(data_str_vec)
		outfile.write("{0:.8g},{1:s}\n".format(f, data_str) )
	
		

def plot_rlgc(freq, R, L, G, C, structure_string):
	freq_ghz = freq/1e9
	
	pl.figure(1, figsize=(9,13) )
	pl.clf()
	ax1 = pl.subplot(4,1,1)
	pl.plot(freq_ghz, R, "b", linewidth=2)
	pl.xlabel("Frequency (GHz)")
	#pl.ylabel("Resistance (Ohms)")
	pl.ylabel("R ($\Omega$/m)")
	ax1.ticklabel_format(axis='y', style='sci', scilimits=(-2,2))
	
	ax2 = pl.subplot(4,1,2)
	pl.plot(freq_ghz, L, "b", linewidth=2)
	pl.xlabel("Frequency (GHz)")
	#pl.ylabel("Inductance (H)")
	pl.ylabel("L (H/m)")
	ax2.ticklabel_format(axis='y', style='sci', scilimits=(-2,2))
	
	ax3 = pl.subplot(4,1,3)
	pl.plot(freq_ghz, G, "b", linewidth=2)
	pl.xlabel("Frequency (GHz)")
	#pl.ylabel("Conductance (S)")
	pl.ylabel("G (S/m)")
	ax3.ticklabel_format(axis='y', style='sci', scilimits=(-2,2))
	
	ax4 = pl.subplot(4,1,4)
	pl.plot(freq_ghz, C, "b", linewidth=2)
	pl.xlabel("Frequency (GHz)")
	#pl.ylabel("Capacitance (F)")
	pl.ylabel("C (F/m)")
	ax4.ticklabel_format(axis='y', style='sci', scilimits=(-2,2))
	
	pl.savefig(structure_string + "_RLGC.pdf")
	
	
	
def plot_s_params(freq, Sdb, Sdeg, structure_string):
	freq_ghz = freq/1e9
	
	S11_db = np.zeros( (len(Sdb)) )
	S12_db = np.zeros( (len(Sdb)) )
	S21_db = np.zeros( (len(Sdb)) )
	S22_db = np.zeros( (len(Sdb)) )
	
	S11_deg = np.zeros( (len(Sdb)) )
	S12_deg = np.zeros( (len(Sdb)) )
	S21_deg = np.zeros( (len(Sdb)) )
	S22_deg = np.zeros( (len(Sdb)) )
	
	for idx in range(len(Sdb)):
		S11_db[idx] = Sdb[idx][0][0]
		S12_db[idx] = Sdb[idx][0][1]
		S21_db[idx] = Sdb[idx][1][0]
		S22_db[idx] = Sdb[idx][1][1]
		
		S11_deg[idx] = Sdeg[idx][0][0]
		S12_deg[idx] = Sdeg[idx][0][1]
		S21_deg[idx] = Sdeg[idx][1][0]
		S22_deg[idx] = Sdeg[idx][1][1]
		
	pl.figure(1, figsize=(8.5,11) )
	pl.clf()
	pl.subplot(2,1,1)
	pl.hold(True)
	pl.plot(freq_ghz, S11_db, 'b', linewidth=2, label="S11")
	pl.plot(freq_ghz, S22_db, 'g', linewidth=2, label="S22")
	pl.xlabel("Frequency (GHz)")
	pl.ylabel("S Parameters (DB)")
	pl.grid()
	pl.legend()
	
	pl.subplot(2,1,2)
	pl.hold(True)
	pl.plot(freq_ghz, S12_db, 'b', linewidth=2, label="S12")
	pl.plot(freq_ghz, S21_db, 'g', linewidth=2, label="S21")
	pl.xlabel("Frequency (GHz)")
	pl.ylabel("S Parameters (DB)")
	pl.grid()
	pl.legend()
	
	pl.savefig(structure_string + "_Sdb.pdf")
	
	pl.figure(2)
	pl.clf()
	pl.subplot(2,1,1)
	pl.hold(True)
	pl.plot(freq_ghz, S11_deg, 'b', linewidth=2, label="S11")
	pl.plot(freq_ghz, S22_deg, 'g', linewidth=2, label="S22")
	pl.xlabel("Frequency (GHz)")
	pl.ylabel("S Parameter Phase (Degrees)")
	pl.grid()
	pl.legend()
	
	pl.subplot(2,1,2)
	pl.hold(True)
	pl.plot(freq_ghz, S12_deg, 'b', linewidth=2, label="S12")
	pl.plot(freq_ghz, S21_deg, 'g', linewidth=2, label="S21")
	pl.xlabel("Frequency (GHz)")
	pl.ylabel("S Parameter Phase (Degrees)")
	pl.grid()
	pl.legend()
	
	pl.savefig(structure_string + "_Sdeg.pdf")
	
	
	

			

def distributed_rlgc_from_abcd(length_m, freq, abcd_mat_array, z0_probe=50):
	# length_m:	(m)	Length of structure being measured
	# s2p_filename: (str)	s2p filename
	# z0_probe:	(Ohms)	Impedance of network analyzer/probes. 50 Ohm default.

	gamma = np.zeros( (len(abcd_mat_array)), dtype=complex)
	Zc = np.zeros( (len(abcd_mat_array)), dtype=complex)
	d_vec = np.zeros( (len(abcd_mat_array)), dtype=complex)
	b_vec = np.zeros( (len(abcd_mat_array)), dtype=complex)
	
	R = np.zeros( (len(abcd_mat_array)) )
	L = np.zeros( (len(abcd_mat_array)) )
	G = np.zeros( (len(abcd_mat_array)) )
	C = np.zeros( (len(abcd_mat_array)) )
	losstan = np.zeros( (len(abcd_mat_array)) )
	attenuation = np.zeros( (len(abcd_mat_array)) )
	
	for idx in range(len(abcd_mat_array)):
		abcd = abcd_mat_array[idx]
		
		d_vec[idx] = abcd[1][1]
		b_vec[idx] = abcd[1][0] # this is actually the C from abcd
		
		gamma[idx] = 1/length_m*np.arccosh(d_vec[idx])
		Zc[idx] = b_vec[idx]**(-1) * np.sinh(gamma[idx] * length_m)
		
		R[idx] = (gamma[idx] * Zc[idx]).real
		L[idx] = 1/2/math.pi/freq[idx] * ( (gamma[idx]*Zc[idx]).imag)
		G[idx] = (gamma[idx] / Zc[idx]).real
		C[idx] = 1/2/math.pi/freq[idx] * ( (gamma[idx]/Zc[idx]).imag)
		
		losstan[idx] = ( (gamma[idx]/Zc[idx]).real) / ( (gamma[idx]/Zc[idx]).imag)
		attenuation[idx] = 20*np.log10( abs(np.exp( -gamma[idx] * length_m )) )


#	R = ( gamma * Zc).real
#	L = 1/2/math.pi/freq * ((gamma * Zc).imag )
#	G = (gamma/Zc).real
#	C = 1/2/math.pi/freq * (gamma/Zc).imag
#	losstan = (gamma/Zc).real / (gamma/Zc).imag
#
#	attenuation = 20*np.log10( abs(np.exp(-gamma*length_m)) )

	return ( freq, R, L, G, C, gamma, attenuation, losstan, Zc )
	
def distributed_rlgc_from_sdb(length_m, freq, Sdb, Sdeg, z0_probe=50):
	# length_m:	(m)	Length of structure being measured
	# s2p_filename: (str)	s2p filename
	# z0_probe:	(Ohms)	Impedance of network analyzer/probes. 50 Ohm default.
	
	Sri_mat = np.zeros( (len(Sdb),2,2), dtype=complex)
	
	for idx in range(len(Sdb)):
		Sdb_mat = Sdb[idx]
		Sdeg_mat = Sdeg[idx]
		
		Sri_mat[idx][0][0] = 10**(Sdb_mat[0][0]/20) * ( np.cos(Sdeg_mat[0][0]*np.pi/180) + 1j*np.sin(Sdeg_mat[0][0]*np.pi/180) )
		Sri_mat[idx][0][1] = 10**(Sdb_mat[0][1]/20) * ( np.cos(Sdeg_mat[0][1]*np.pi/180) + 1j*np.sin(Sdeg_mat[0][1]*np.pi/180) )
		Sri_mat[idx][1][0] = 10**(Sdb_mat[1][0]/20) * ( np.cos(Sdeg_mat[1][0]*np.pi/180) + 1j*np.sin(Sdeg_mat[1][0]*np.pi/180) )
		Sri_mat[idx][1][1] = 10**(Sdb_mat[1][1]/20) * ( np.cos(Sdeg_mat[1][1]*np.pi/180) + 1j*np.sin(Sdeg_mat[1][1]*np.pi/180) )
		
	abcd_mat_array = sri2abcd(Sri_mat)
	
	

	gamma = np.zeros( (len(abcd_mat_array)), dtype=complex)
	Zc = np.zeros( (len(abcd_mat_array)), dtype=complex)
	d_vec = np.zeros( (len(abcd_mat_array)), dtype=complex)
	b_vec = np.zeros( (len(abcd_mat_array)), dtype=complex)
	
	#R = np.zeros( (len(abcd_mat_array)) )
	#L = np.zeros( (len(abcd_mat_array)) )
	#G = np.zeros( (len(abcd_mat_array)) )
	#C = np.zeros( (len(abcd_mat_array)) )
	#losstan = np.zeros( (len(abcd_mat_array)) )
	#attenuation = np.zeros( (len(abcd_mat_array)) )
	
	for idx in range(len(abcd_mat_array)):
		abcd = abcd_mat_array[idx]
		
		d_vec[idx] = abcd[1][1]
		#b_vec[idx] = abcd[0][1] # B vector (used in the matlab script
		b_vec[idx] = abcd[1][0] # C vector (what I think needs to be used for Zc extraction)
		gamma[idx] = 1/length_m*np.arccosh(d_vec[idx])
		Zc[idx] = np.sinh(gamma[idx] * length_m)/b_vec[idx]
		#R[idx] = (gamma[idx] * Zc[idx]).real
		#L[idx] = 1/2/math.pi/freq[idx] * ( (gamma[idx] * Zc[idx]).imag)
		#G[idx] = (gamma[idx] / Zc[idx]).real
		#C[idx] = 1/2/math.pi/freq[idx] * ((gamma[idx]/Zc[idx]).imag)
		
		#losstan[idx] = ( (gamma[idx]/Zc[idx]).real) / ( (gamma[idx]/Zc[idx]).imag)
		#attenuation[idx] = 20*np.log10( abs(np.exp( -gamma[idx] * length_m )) )
		
		#print(gamma[idx] * Zc[idx])
		#print(1/2/math.pi/freq[idx] * ( (gamma[idx] * Zc[idx]).imag))


	R = ( gamma * Zc).real
	L = 1/2/math.pi/freq * ((gamma * Zc).imag )
	G = (gamma/Zc).real
	C = 1/2/math.pi/freq * (gamma/Zc).imag
	losstan = (gamma/Zc).real / (gamma/Zc).imag

	attenuation = 20*np.log10( abs(np.exp(-gamma*length_m)) )

	return ( freq, R, L, G, C, gamma, attenuation, losstan, Zc )
	
def distributed_rlgc_from_sri(length_m, freq, Sri, z0_probe=50):
	# length_m:	(m)	Length of structure being measured
	# s2p_filename: (str)	s2p filename
	# z0_probe:	(Ohms)	Impedance of network analyzer/probes. 50 Ohm default.

	gamma = np.zeros( (len(Sri)), dtype=complex)
	Zc =    np.zeros( (len(Sri)), dtype=complex)
	
	
	for idx in range(len(Sri)):
		
		S11 = Sri[idx][0][0]
		#S12 = Sri[idx][0][1] # Not needed
		S21 = Sri[idx][1][0]
		#S22 = Sri[idx][1][1] # not needed
		
		K = np.sqrt( ((S11**2 - S21**2 + 1)**2 - (2*S11)**2)/(2*S21**2))
		alpha = ( (1 - S11**2 + S21**2)/(2*S21) + K)**(-1)
		gamma[idx] = -1/length_m * np.log(alpha)
		
		Zc[idx] = np.sqrt( z0_probe**2 * ( (1+S11)**2 - S21**2)/( (1-S11)**2 - S21**2) )
		


	R = ( gamma * Zc).real
	L = 1/2/math.pi/freq * ((gamma * Zc).imag )
	G = (gamma/Zc).real
	C = 1/2/math.pi/freq * (gamma/Zc).imag
	losstan = (gamma/Zc).real / (gamma/Zc).imag

	attenuation = 20*np.log10( abs(np.exp(-gamma*length_m)) )

	return ( freq, R, L, G, C, gamma, attenuation, losstan, Zc )


def lumped_rlgc_from_Network(net, z0_probe=50):
	# s2p_filename: (str)	s2p filename
	# z0_probe:	(Ohms)	Impedance of network analyzer/probes. 50 Ohm default.

	freq = net.f

	Z = net.z
	Y = net.y

	Zdiff = np.zeros( (len(Z)), dtype=complex)
	Ycomm = np.zeros( (len(Z)), dtype=complex)
	for idx in range(len(Zdiff)):
		zz = Z[idx]
		yy = Y[idx]
		
		Zdiff[idx] = z0_probe*(zz[0,0] - zz[0,1] - zz[1,0] + zz[1,1])
		Ycomm[idx] = yy[0,0] + yy[0,1] + yy[1,0] + yy[1,1]

	R = Zdiff.real
	L = 1/2/math.pi/freq *(Zdiff.imag)
	G = Ycomm.real
	C = 1/2/math.pi/freq * (Ycomm.imag)

	return (freq, R, L, G, C, Zdiff, Ycomm, net)


def abcd2s(abcd_struct, Z01, Z02):
	# convert ABCD matrix to S matrix in real/imag format

	R01 = Z01.real
	R02 = Z02.real
	num_freqs = len(abcd_struct)
	S = np.zeros( (num_freqs, 2, 2), dtype=complex )
	for idx in range(len(abcd_struct)):
		mat = abcd_struct[idx]
		A = mat[0][0]
		B = mat[0][1]
		C = mat[1][0]
		D = mat[1][1]

		denom = (A*Z02 + B + C*Z01*Z02 + D*Z01)

		S11 = ( A*Z02 + B - C*np.conj(Z01)*Z02 - D*np.conj(Z01) ) / denom
		S12 = ( 2*(A*D - B*C)*np.sqrt(R01*R02) ) / denom
		S21 = ( 2*np.sqrt(R01*R02) ) / denom
		S22 = (-A*np.conj(Z02) + B - C*Z01*np.conj(Z02) + D*Z01 ) / denom

		S[idx][0][0] = S11
		S[idx][0][1] = S12
		S[idx][1][0] = S21
		S[idx][1][1] = S22


	return S

def abcd2s_alt(abcd_struct, Z01, Z02):
	# convert ABCD matrix to S matrix in real/imag format

	#R01 = Z01.real
	#R02 = Z02.real
	Z0 = Z01

	num_freqs = len(abcd_struct)
	S = np.zeros( (num_freqs, 2, 2), dtype=complex )
	for idx in range(len(abcd_struct)):
		mat = abcd_struct[idx]
		A = mat[0][0]
		B = mat[0][1]
		C = mat[1][0]
		D = mat[1][1]

		denom = (A + B/Z0 + C*Z0 + D)

		S11 = ( A + B/Z0 - C*Z0 - D ) / denom
		S12 = ( 2*(A*D - B*C) ) / denom
		S21 = ( 2 ) / denom
		S22 = (-A + B/Z0 - C*Z0 + D ) / denom

		S[idx][0][0] = S11
		S[idx][0][1] = S12
		S[idx][1][0] = S21
		S[idx][1][1] = S22


	return S
	

def sri2abcd(s_struct, Z01=50, Z02=50):
	# Convert Sparams in Real/Imag format to ABCD matrix
	R01 = Z01.real
	R02 = Z02.real
	num_freqs = len(s_struct)
	abcd = np.zeros( (num_freqs, 2, 2), dtype=complex )
	for idx in range(len(s_struct)):
		mat = s_struct[idx]
		S11 = mat[0][0]
		S12 = mat[0][1]
		S21 = mat[1][0]
		S22 = mat[1][1]

		denom = 2*S21*np.sqrt(R01*R02)
		
		
		A = ( (np.conj(Z01) + S11*Z01)*(1-S22)+S12*S21*Z01 ) / denom
		B = ( (np.conj(Z01) + S11*Z01)*(np.conj(Z02)+S22*Z02)-S12*S21*Z01*Z02 ) / denom
		C = ( (1-S11)*(1-S22)-S12*S21 ) / denom
		D = ( (1-S11)*(np.conj(Z02)+S22*Z02) + S12*S21*Z02 ) / denom

		abcd[idx][0][0] = A
		abcd[idx][0][1] = B
		abcd[idx][1][0] = C
		abcd[idx][1][1] = D

	return abcd
	
def sri2abcd_alt(s_struct, Z01=50, Z02=50):
	# Convert Sparams in Real/Imag format to ABCD matrix
	R01 = Z01.real
	R02 = Z02.real
	Z0 = Z01
	num_freqs = len(s_struct)
	abcd = np.zeros( (num_freqs, 2, 2), dtype=complex )
	for idx in range(len(s_struct)):
		mat = s_struct[idx]
		S11 = mat[0][0]
		S12 = mat[0][1]
		S21 = mat[1][0]
		S22 = mat[1][1]
		
		
		A = ( (1+S11)*(1-S22) + S12*S21 ) / (2*S21)
		B = Z0*( ((1+S11)*(1+S22) - S12*S21) / (2*S21) )
		C = ( (1-S11)*(1-S22) - S12*S21) / (2*S21*Z0) 
		D = ( (1-S11)*(1+S22) + S12*S21) / (2*S21)

		abcd[idx][0][0] = A
		abcd[idx][0][1] = B
		abcd[idx][1][0] = C
		abcd[idx][1][1] = D

	return abcd


def sdb2sri(sdb_struct, sdeg_struct):
	# convert DB/DEG to real/imag
	num_freqs = len(sdb_struct)
	Sri = np.zeros( (num_freqs, 2, 2), dtype=complex)

	for idx in range(len(sdb_struct)):
		db_mat = sdb_struct[idx]
		S11_db = db_mat[0][0]
		S12_db = db_mat[0][1]
		S21_db = db_mat[1][0]
		S22_db = db_mat[1][1]

		deg_mat = sdeg_struct[idx]
		S11_deg = deg_mat[0][0]
		S12_deg = deg_mat[0][1]
		S21_deg = deg_mat[1][0]
		S22_deg = deg_mat[1][1]

		S11 = 10**(S11_db/20) * np.complex( math.cos(S11_deg*math.pi/180), math.sin(S11_deg*math.pi/180) )
		S12 = 10**(S12_db/20) * np.complex( math.cos(S12_deg*math.pi/180), math.sin(S12_deg*math.pi/180) )
		S21 = 10**(S21_db/20) * np.complex( math.cos(S21_deg*math.pi/180), math.sin(S21_deg*math.pi/180) )
		S22 = 10**(S22_db/20) * np.complex( math.cos(S22_deg*math.pi/180), math.sin(S22_deg*math.pi/180) )

		Sri[idx][0][0] = S11
		Sri[idx][0][1] = S12
		Sri[idx][1][0] = S21
		Sri[idx][1][1] = S22

	return Sri



def sdb2abcd(sdb_struct, sdeg_struct):

	sri = sdb2sri(sdb_struct, sdeg_struct)
	abcd = sri2abcd(sri)

	return abcd
	


def sri2sdb(sri_struct):
	# convert S params from Real/Imag to DB/Deg
	num_freqs = len(sri_struct)
	Sdb = np.zeros( (num_freqs, 2, 2))
	Sdeg = np.zeros( (num_freqs, 2, 2))

	for idx in range(len(sri_struct)):
		ri_mat = sri_struct[idx]
		S11_ri = ri_mat[0][0]
		S12_ri = ri_mat[0][1]
		S21_ri = ri_mat[1][0]
		S22_ri = ri_mat[1][1]


		S11_db = 20*np.log10( np.abs(S11_ri) )
		S12_db = 20*np.log10( np.abs(S12_ri) )
		S21_db = 20*np.log10( np.abs(S21_ri) )
		S22_db = 20*np.log10( np.abs(S22_ri) )

		S11_deg = np.arcsin( S11_ri.imag / np.abs(S11_ri) ) * 180/math.pi
		S12_deg = np.arcsin( S12_ri.imag / np.abs(S12_ri) ) * 180/math.pi
		S21_deg = np.arcsin( S21_ri.imag / np.abs(S21_ri) ) * 180/math.pi
		S22_deg = np.arcsin( S22_ri.imag / np.abs(S22_ri) ) * 180/math.pi
		
#		if ( S11_ri.real < 0 ) and (S11_ri.imag > 0):
#			S11_deg = 180 - S11_deg
#		if ( S12_ri.real < 0 ) and (S12_ri.imag > 0):
#			S12_deg = 180 - S12_deg
#		if ( S21_ri.real < 0 ) and (S21_ri.imag > 0):
#			S21_deg = 180 - S21_deg
#		if ( S22_ri.real < 0 ) and (S22_ri.imag > 0):
#			S22_deg = 180 - S22_deg
		

		Sdb[idx][0][0] = S11_db
		Sdb[idx][0][1] = S12_db
		Sdb[idx][1][0] = S21_db
		Sdb[idx][1][1] = S22_db

		Sdeg[idx][0][0] = S11_deg
		Sdeg[idx][0][1] = S12_deg
		Sdeg[idx][1][0] = S21_deg
		Sdeg[idx][1][1] = S22_deg

	return (Sdb, Sdeg)



def get_pad_abcd(pad_L_s2p_filename, pad_2L_s2p_filename, z0_probe=50):
	# (freq, abcd_pad, abcd_pad_inv, Sri_pad, Sdb_pad, Sdeg_pad, net_pad) = get_pad_abcd(pad_L_s2p_filename, pad_2L_s2p_filename, z0_probe=50)
	net_pad_L = rf.Network(pad_L_s2p_filename, z0=z0_probe) # d
	net_pad_2L = rf.Network(pad_2L_s2p_filename, z0=z0_probe) # c

	# ABCD matrices
	abcd_L = sdb2abcd(net_pad_L.s_db, net_pad_L.s_deg) # ABCD matrix for complete L structure used for pad deembedding (Pad - line - Pad )
	abcd_2L = sdb2abcd(net_pad_2L.s_db, net_pad_2L.s_deg) # ABCD matrix for complete 2L structure used for pad deembedding (Pad - line - line - Pad)
	
	abcd_pad = [] # ABCD matrix structure for pad
	abcd_pad_inv = [] # inverse abcd matrix structure for pad
	
	# iterating across each frequency point
	for idx, abcd_L_mat in enumerate(abcd_L):
		abcd_2L_mat = abcd_2L[idx]
		
		abcd_L_inv = la.inv(abcd_L_mat)
		abcd_P_squared = la.inv( np.dot( abcd_L_inv, np.dot( abcd_2L_mat, abcd_L_inv) ) ) # PP = ( ML^-1 * M2L * ML^-1 )^-1
		abcd_P = sla.sqrtm(abcd_P_squared) # ABCD matrix of the pad (single pad) for this frequency
		abcd_P_inv = la.inv(abcd_P)
		
		abcd_pad.append(abcd_P)
		abcd_pad_inv.append(abcd_P_inv)
		
	Sri_pad = abcd2s(abcd_pad, z0_probe, z0_probe)
	(Sdb_pad, Sdeg_pad) = sri2sdb(Sri_pad)
	freq = net_pad_L.f
	
	net_pad = rf.Network( f=freq*1e-9, s=Sri_pad, z0=50)
	
	return (freq, abcd_pad, abcd_pad_inv, Sri_pad, Sdb_pad, Sdeg_pad, net_pad)


	
def deembed_pads_from_measurement(abcd_pad_inv, abcd_dut, z0_probe = 50):
	# (abcd_dut_deembedded, Sri_dut, Sdb_dut, Sdeg_dut) = deembed_pads_from_measurement(abcd_pad_inv, abcd_dut, z0_probe = 50)
	
	abcd_dut_deembedded = []
	
	for idx, Pinv in enumerate(abcd_pad_inv):
		abcd_dut_deembedded_f = np.dot( Pinv, np.dot( abcd_dut, Pinv) )
		abcd_dut_deembedded.append(abcd_dut_deembedded_f)
		
	Sri_dut = abcd2s(abcd_dut, z0_probe, z0_probe)
	(Sdb_dut, Sdeg_dut) = sri2sdb(Sri_dut)
	
		
	return (abcd_dut_deembedded, Sri_dut, Sdb_dut, Sdeg_dut)
	
	
	
def extract_rlcg_from_measurement( freq, length_m, abcd_pad_inv, abcd_dut, z0_probe = 50, method="distributed", skip_deembed=False):
	# (freq, R, L, G, C) = extract_rlcg_from_measurement( freq, length_m, abcd_pad_inv, abcd_dut, z0_probe = 50, method="distributed")
	
	if not skip_deembed:
		(abcd_dut_deembedded, Sri_dut, Sdb_dut, Sdeg_dut) = deembed_pads_from_measurement(abcd_pad_inv, abcd_dut, z0_probe)
	else:
		Sri_dut = abcd2s(abcd_dut, z0_probe, z0_probe)
		(Sdb_dut, Sdeg_dut) = sri2sdb(Sri_dut)
	
	if method == "distributed":		
			(freq, R, L, G, C, gamma, attenuation, losstan, Zc) = distributed_rlgc_from_sdb(length_m, freq, Sdb_dut, Sdeg_dut, z0_probe)
	elif method == "lumped":
		net_dut = rf.Network( f=freq*1e-9, s=Sri_dut, z0=z0_probe)
		(freq, R, L, G, C, Zdiff, Ycomm, net) = lumped_rlgc_from_Network(net_dut, z0_probe)
	elif method == "distributed_abcd":
		(freq, R, L, G, C, gamma, attenuation, losstan, Zc) = distributed_rlgc_from_abcd(length_m, freq, abcd_dut, z0_probe)
	elif method == "distributed_ri":
		(freq, R, L, G, C, gamma, attenuation, losstan, Zc) = distributed_rlgc_from_sdb(length_m, freq, Sri_dut, z0_probe)
		
	return (freq, R, L, G, C)
	



def l2l_deembed_mod(pad_L_s2p_filename, pad_2L_s2p_filename, structure_L_s2p_filename, z0_probe=50):

	net_pad_L = rf.Network(pad_L_s2p_filename, z0=z0_probe) # d
	net_pad_2L = rf.Network(pad_2L_s2p_filename, z0=z0_probe) # c
	net_struct_L = rf.Network(structure_L_s2p_filename, z0=z0_probe) # e

	# ABCD matrices
	M_L = sdb2abcd(net_pad_L.s_db, net_pad_L.s_deg) # ABCD matrix for complete L structure used for pad deembedding (Pad - line - Pad )
	M_2L = sdb2abcd(net_pad_2L.s_db, net_pad_2L.s_deg) # ABCD matrix for complete 2L structure used for pad deembedding (Pad - line - line - Pad)
	S_L = sdb2abcd(net_struct_L.s_db, net_struct_L.s_deg) # ABCD matrix for complete L structure from which we want to remove the pad contribution (Pad - stuff - Pad)

	abcd_L = [] # ABCD matrix structure for transmission line
	
	# iterating across each frequency point
	for idx, M_L_mat in enumerate(M_L):
		M_2L_mat = M_2L[idx]
		
		M_L_inv = la.inv(M_L_mat)
		P_squared = la.inv( np.dot( M_L_inv, np.dot( M_2L_mat, M_L_inv) ) ) # PP = ( ML^-1 * M2L * ML^-1 )^-1
		P = sla.sqrtm(P_squared) # ABCD matrix of the pad (single pad) for this frequency
		P_inv = la.inv(P)
		
		abcd_f = np.dot( P_inv, np.dot( S_L, P_inv) )
		abcd_L.append(abcd_f)
		
	Sri_L = abcd2s(abcd_L, z0_probe, z0_probe)
	(Sdb_L, Sdeg_L) = sri2sdb(Sri_L)
	freq = net_pad_L.f
	
	net_L = rf.Network( f=freq*1e-9, s=Sri_L, z0=50)
	

	return (freq, Sri_L, abcd_L, Sdb_L, Sdeg_L, net_L)


def l2l_deembed(pad_L_s2p_filename, pad_2L_s2p_filename, structure_L_s2p_filename, structure_2L_s2p_filename, z0_probe=50):

	net_pad_L = rf.Network(pad_L_s2p_filename, z0=z0_probe) # d
	net_pad_2L = rf.Network(pad_2L_s2p_filename, z0=z0_probe) # c
	net_struct_L = rf.Network(structure_L_s2p_filename, z0=z0_probe) # e # not needed
	net_struct_2L = rf.Network(structure_2L_s2p_filename, z0=z0_probe) # f

	# ABCD matrices
	TP_2L = sdb2abcd(net_pad_2L.s_db, net_pad_2L.s_deg)
	TP_L = sdb2abcd(net_pad_L.s_db, net_pad_L.s_deg)
	TS_L = sdb2abcd(net_struct_L.s_db, net_struct_L.s_deg)
	TS_2L = sdb2abcd(net_struct_2L.s_db, net_struct_2L.s_deg)


	TL1 = []
	TL2 = []
	
	for idx, tlp_mat in enumerate(TP_L):
		tlpi_mat = la.inv(tlp_mat)
		tp_2l_mat = TP_2L[idx]
		
		TP_L_inner_pre = np.dot( tlpi_mat, np.dot( tp_2l_mat, tlpi_mat ) ) # TLPI_MAT * TS_2L_MAT * TLPI_MAT matrix multiplication
		TP_L_inner = la.inv(TP_L_inner_pre)
		TP1 = sla.sqrtm(TP_L_inner)
		#TL1.append(TP1)
		

		TP1_inv = la.inv(TP1)
		TS_2L_entry = TS_2L[idx]
		TS_L_entry = TS_L[idx]
		TL1_entry = np.dot( TP1_inv, np.dot( TS_L_entry,  TP1_inv ) )
		TL1.append(TL1_entry)
		
		TL2_entry = np.dot( TP1_inv, np.dot( TS_2L_entry, TP1_inv ) )
		TL2.append( TL2_entry )

	abcd_L = TL1
	abcd_2L = TL2
	Sri_L = abcd2s(TL1, z0_probe, z0_probe)
	Sri_2L = abcd2s(TL2, z0_probe, z0_probe)

	(Sdb_L, Sdeg_L) = sri2sdb(Sri_L)
	(Sdb_2L, Sdeg_2L) = sri2sdb(Sri_2L)
	freq = net_pad_L.f
	
	net_L = rf.Network( f=freq*1e-9, s=Sri_L, z0=50)
	net_2L = rf.Network( f=freq*1e-9, s=Sri_2L, z0=50)
	

	return (freq, Sri_L, Sri_2L, abcd_L, abcd_2L, Sdb_L, Sdeg_L, Sdb_2L, Sdeg_2L, net_L, net_2L)


def write_net_db_deg( net, filename):
	outfile = open(filename,'w')

	freq_vec = net.f
	s_db_list = net.s_db
	s_deg_list = net.s_deg

	for idx in range(len(freq_vec)):
		freq = freq_vec[idx]
		s_db_mat = s_db_list[idx]
		S11_db = s_db_mat[0][0]
		S12_db = s_db_mat[0][1]
		S21_db = s_db_mat[1][0]
		S22_db = s_db_mat[1][1]

		s_deg_mat = s_deg_list[idx]
		S11_deg = s_deg_mat[0][0]
		S12_deg = s_deg_mat[0][1]
		S21_deg = s_deg_mat[1][0]
		S22_deg = s_deg_mat[1][1]

		outstr = "{0:.4g},{1:.4g},{2:.4g},{3:.4g},{4:.4g},{5:.4g},{6:.4g},{7:.4g},{8:.4g}\n".format( freq, S11_db, S11_deg, S12_db, S12_deg, S21_db, S21_deg, S22_db, S22_deg)

		outfile.write(outstr)
 


def write_s_db_deg( sdb, sdeg, freq, filename):
	outfile = open(filename,'w')

	freq_vec = freq
	s_db_list = sdb
	s_deg_list = sdeg

	for idx in range(len(freq_vec)):
		freq = freq_vec[idx]
		s_db_mat = s_db_list[idx]
		S11_db = s_db_mat[0][0]
		S12_db = s_db_mat[0][1]
		S21_db = s_db_mat[1][0]
		S22_db = s_db_mat[1][1]

		s_deg_mat = s_deg_list[idx]
		S11_deg = s_deg_mat[0][0]
		S12_deg = s_deg_mat[0][1]
		S21_deg = s_deg_mat[1][0]
		S22_deg = s_deg_mat[1][1]

		outstr = "{0:.8g},{1:.8g},{2:.8g},{3:.8g},{4:.8g},{5:.8g},{6:.8g},{7:.8g},{8:.8g}\n".format( freq, S11_db, S11_deg, S12_db, S12_deg, S21_db, S21_deg, S22_db, S22_deg)

		outfile.write(outstr)


def write_rlgc(freq, R, L, G, C, filename):
	outfile = open(filename, 'w')
	
	for idx, f in enumerate(freq):
		r = R[idx]
		l = L[idx]
		g = G[idx]
		c = C[idx]
		
		outstr = "{0:.8g},{1:.8g},{2:.8g},{3:.8g},{4:.8g}\n".format(f, r, l, g, c)
		outfile.write(outstr)
		

if (__name__ == "__main__"):
	main()
