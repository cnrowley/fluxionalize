#!/usr/bin/python
import subprocess, os, csv, shutil, re, sys, getopt, tarfile
from itertools import izip
from contextlib import closing

#converts SMILES string to 3D structure .mol2 output
def call_babel(file_type, input):
        if file_type =='SMILES':
                command_line = 'obabel -:"'+input+'" -O mol.pdb --gen3d --conformer --systematic --ff GAFF'
        else:
                command_line = 'obabel -i"'+file_type+' '+ input+'" -O mol.pdb --gen3d --conformer --systematic --ff GAFF'
        babelcmd=subprocess.Popen(command_line, stdout=subprocess.PIPE,stderr=subprocess.PIPE, shell=True)
        babelout, babelerr = babelcmd.communicate()
        if not re.match(r'^1 ', babelerr) :
                print("Error with SMILES String: %s") %babelerr
                return

#fixes pdb from call_babel
def fix_pdb():
        file_in = open('mol.pdb', 'r')
        file_out = open('mol_fix.pdb', 'w')
        charge=0
        for line in file_in:
                temp = line.split()
                if (temp[0]== 'HETATM' or temp[0]=='ATOM'):
                        temp[0]='ATOM'
                        temp[2]=temp[2][0]
                        temp[3]='UNK'
                        if (len(temp))==11:
                                temp.extend(['0'])
                                temp[11]=temp[10]
                                temp[10]=temp[9]
                                temp[9]=temp[8]
                                temp[8]=temp[7]
                                temp[7]=temp[6]
                                temp[6]=temp[5]

                        temp[5]='0'
                        file_out.write('{0:>4}  {1:>5}  {2:<4}{3:>3} {4:>1}{5:>4}      {6:>6}{7:>8}{8:>8}{9:>6}{10:>6}          {11:>2}{12:>1}\n'.format(temp[0],temp[1],temp[2],temp[3],temp[4],temp[5],temp[6],
                                        temp[7],temp[8],temp[9],temp[10],temp[11][0], temp[11][1:]))
                        charge=charge+temp[11].count('+')
                        charge=charge-temp[11].count('-')
                else:
                        file_out.write(line)
        file_out.close()
        file_in.close()
        print(charge)
        return(charge)

#generates charmm readable files
def call_antechamber(netcharge):
        find_amber = subprocess.Popen("which antechamber", stdout=subprocess.PIPE,stderr=subprocess.PIPE, shell=True)
        antechmbr, err= find_amber.communicate()
        antecmd = antechmbr.strip()+ " -fi pdb -i mol_fix.pdb -fo charmm -o mol -c bcc -nc "+str(netcharge)
        ante = subprocess.Popen(antecmd, shell=True).wait()
        ant_pdbcmd = antechmbr.strip()+" -fi pdb -i mol_fix.pdb -fo pdb -o molnew.pdb -rn MOL "+str(netcharge)
        ant_pdb = subprocess.Popen(ant_pdbcmd, shell=True).wait()

#modifies prm to add LJ potential to hydrogens lacking it
def fix_prm():
        file_in = open('mol.prm', 'r')
        file_out = open('mol_fix.prm', 'w')
        for line in file_in:
                temp=line.split()
                if(len(temp)==7 and temp[2]=='-0.0000'):
                        temp[2]='-0.0157'
                        temp[3]='1.3870'
                        temp[5]='-0.0078'
                        temp[6]='1.3870'
                        file_out.write('{0:>2}      {1:>4}   {2:>7}    {3:>6}      {4:>4}   {5:>7}    {6:>6}\n'.format(temp[0], temp[1], temp[2], temp[3], temp[4], temp[5], temp[6]))

                else:
                        file_out.write(line)
        file_in.close()
        file_out.close()
        shutil.copy("mol_fix.prm", "mol.prm")
        os.remove("mol_fix.prm")


#calls vmd's psfgen to generate psf and pdb files
def call_psfgen():
        file_out = open ('mol_psfgen.pgn', 'w')
        file_out.write("package require psfgen\npackage require autoionize\ntopology mol.inp\ntopology mol.rtf\nsegment MOL {pdb molnew.pdb}\ncoordpdb molnew.pdb MOL\nguesscord\nwritepdb mol.pdb\n"+
                        "writepsf mol.psf\nautoionize -psf mol.psf -pdb mol.pdb -neutralize -o mol\nquit vmd")
        file_out.close()
        psf_cmds = "vmd -dispdev text -eofexit <mol_psfgen.pgn> temp.out 2>temp-error.out"
        psf=subprocess.Popen(psf_cmds, shell=True).wait()

#calls VMD to add solvation box
def solvate_cmds():
        file_out = open('mol_solvate.tcl', 'w')
        file_out.write("package require solvate\nsolvate mol.psf mol.pdb -t 10 -o mol_wb\nquit vmd")
        file_out.close()

        solv_cmds = "vmd -dispdev text -eofexit <mol_solvate.tcl> temp.out 2> temp-error.out"
        solv=subprocess.Popen(solv_cmds, shell=True).wait()

#makes xsc file for namd
def make_xsc():
        file_in = open('mol_wb.pdb', 'r')
        file_out = open('mol.xsc', 'w')

        for line in file_in:
                if line.startswith("CRYST1"):
                        size = line[9:15]

        file_out.write("#NAMD extended system configuration restart file\n#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z s_x s_y s_z s_u s_v s_w\n"
                        + "0 "+size+ " 0 0 0 "+size+ " 0 0 0 "+size+ " 0 0 0 0 0 0 0 0 0)")
        file_in.close()
        file_out.close()

#edit pdb to restrain center of mass
def rest_vmd():
        file_out = open('mol_rest.tcl', 'w')
        file_out.write('mol addfile mol_wb.pdb\nset selall [atomselect top "all"]\nset selsolute [atomselect top "segid MOL"]\n$selall set occupancy 0.0\n$selsolute set occupancy 1.0\n'
                        +'$selall writepdb molref.pdb\nquit vmd')
        file_out.close()

        rest_cmds = "vmd -dispdev text -eofexit <mol_rest.tcl> temp.out 2> temp-error.out"
        rest = subprocess.Popen(rest_cmds, shell=True).wait()

#creats colvar to restrain center of mass
def rest_colvars():
        file_out = open('colvars.tcl', 'w')
        file_out.write('colvar {\n\tname molcom\n\tdistance {\n\t\tgroup1 {\n\t\t\tatomsFile molref.pdb\n\t\t\tatomsCol O\n\t\t\tatomsColValue 1.0\n\t\t}\n\n\t\tgroup2 {\n\t\t\tdummyAtom (0.000, 0.000, 0.000)'
                        +'\n\t\t}\n\t}\n}\n\nharmonic {\n\tname molrestcom\n\tcolvars molcom\n\tcenters 0.0\n\tforceConstant 5.0\n}')

        file_out.close()

#calls namd for reg
def call_namd_exp(option, num_processors):
        namd_cmds = "/opt/openmpi/1.4.5/gcc/bin/mpirun -np "+num_processors+" namd2 mol"+option+"-nvt.namd >mol"+option+"-nvt.out"
        namd=subprocess.Popen(namd_cmds, shell=True).wait()
        namd_cmds = "/opt/openmpi/1.4.5/gcc/bin/mpirun -np "+num_processors+" namd2 mol"+option+"-npt.namd >mol"+option+"-npt.out"
        namd=subprocess.Popen(namd_cmds, shell=True).wait()

#calls namd for gbis, and gas
def call_namd(option, num_processors):
        namd_cmds = "/opt/openmpi/1.4.5/gcc/bin/mpirun -np "+num_processors+" namd2 mol"+option+".namd >mol"+option+".out"
        namd=subprocess.Popen(namd_cmds, shell=True).wait()

#extracts volume and potential energy from namd.out file to mol_vol.txt
def calc_voltrend(option):
        file_in = open('mol'+option+'.out', 'r')
        file_out = open('mol'+option+'_namd.txt', 'w')
        vol = ['VOLUME']
        pot = ['POTENTIAL ENERGY']
        count = ['TIMESTEPS']

        for line in file_in:
                if line.startswith("ENERGY"):
                        energy = line.split()
                        vol.append(energy[18])
                        pot.append(energy[13])
                        count.append(energy[1])
        writer=csv.writer(file_out)
        writer.writerows(izip(count,vol, pot))
        file_in.close()
        file_out.close()
        
        graph_trends("pe"+option, option)
        graph_trends("vol"+option, option)

#creates graphs of Potential Energy vs Timesteps and Volume vs. Timesteps
def graph_trends(title, option):
        graph_out= open ('mol_'+title+'.p', 'w')
        if re.match(r'^pe', title):
                graph_out.write('set title "Potential Energy vs. Time Steps"\nset datafile separator ","\nset xlabel "Timesteps"\nset ylabel "Potential Energy"\nunset key\n'
                                +'set autoscale\nset terminal png size 800,600 enhanced font "Helvetica,10"\nset output "mol_'+title+'.png"\nplot "mol'+option+'_namd.txt" using 1:3 with lines\nexit')
        elif re.match(r'^vol', title):
                graph_out.write('set title "Volume vs. Time Steps"\nset datafile separator ","\nset xlabel "Timesteps"\nset ylabel "Volume"\nunset key\n'
                                +'set autoscale\nset terminal png size 800,600 enhanced font "Helvetica,10"\nset output "mol_'+title+'.png"\nplot "mol'+option+'_namd.txt" using 1:2 with lines\nexit')
        else:
                print("Error!")
        graph_out.close()

        gnuplot_cmds = "gnuplot>load 'mol_'"+title+"'.p'"
        gnuplot=subprocess.Popen(gnuplot_cmds, shell = True).wait()

#performs REMD using user input for number of replicas and number of runs, output folder dynamically generated
def namd_remd(option, file_extension,pdb_extension, num_processors):
        num_reps = "24"
        num_runs = "10000"

        folder_out = 'output'+option
        if os.path.exists(folder_out):
                shutil.rmtree(folder_out)
        os.mkdir(folder_out)
        for i in range(int(num_reps)):
                os.mkdir(folder_out+'/%d' %i)

        job_out = open('job'+option+'.conf', 'w')
        job_out.write('source mol_rep'+option+'.conf\n#prevents VMD from reading replica.namd by trying command only NAMD has\nif {! [catch numPes]} '+
                '{source replica.namd}')
        job_out.close()
        conf_out = open('mol_rep'+option+'.conf', 'w')
        conf_out.write('set num_replicas '+num_reps+'\nset min_temp 298\nset max_temp 500\nset steps_per_run 1000\nset num_runs '+num_runs+'\n\nset runs_per_frame 1\nset frames_per_restart 1\n'+
                        'set namd_config_file "mol_rep'+option+'.namd"\nset output_root "'+folder_out+'/%s/mol";\n\nset psf_file "mol'+file_extension+'.psf"\nset pdb_file "mol'+pdb_extension+'.pdb"')
        conf_out.close()

        remd_cmds =  "/opt/openmpi/1.4.5/gcc/bin/mpirun -np "+num_processors+" namd2 +replicas "+num_reps+" job"+option+".conf +stdout "+folder_out+"/%d/job0.%d.log >&job"+option+".out"

        remd=subprocess.Popen(remd_cmds, shell=True).wait()

#sorts replicas
def sort_replicas(option):
        sort_reps_cmds = "sortreplicas output"+option+"/%d/mol.job0 24 1"
        sort_reps = subprocess.Popen(sort_reps_cmds, shell=True).wait()

#measures clusters then creates pdb and files for clusters from lowest temp replica
def vmd_cluster(option):
        clust_out = 'clusters'+option
        if os.path.exists(clust_out):
                shutil.rmtree(clust_out)
        os.mkdir(clust_out)
        clust_cmds = "vmd -dispdev text -e mol_cluster"+option+".tcl>cluster.log"
        clust=subprocess.Popen(clust_cmds, shell=True).wait()

        conf_out = 'conf'+option
        if os.path.exists(conf_out):
                shutil.rmtree(conf_out)
        os.mkdir(conf_out)
        conf_file = open('mol_conf'+option+'.tcl', 'w')
        conf_file.write('#creates pdb files for the clusters from the 1st replica\nfor {set i 0} {$i <= 4} {incr i} {\n set dcd "clusters'+option+'/cluster0.$i.dcd"\n set psf "mol.psf"\n'
                        +' mol load psf $psf dcd $dcd\n set selconf [atomselect top "all"]\n $selconf writepdb conf'+option+'/cluster0.$i.pdb\n}\nexit')
        conf_file.close()

        conf_cmds = "vmd -dispdev text -e mol_conf"+option+".tcl>conf.log"
        conf=subprocess.Popen(conf_cmds, shell=True).wait()

        rmsd_graph = open('mol_rmsdtt'+option+'.p', 'w')
        rmsd_graph.write('set title "RMSD Trajectory"\nset xlabel "Frame"\nset ylabel "RMSD"\nunset key\nset terminal png size 800,600 enhanced font "Helvetica,10"\nset output "mol_rmsdtt'+option+'.png"\n'+
                        'plot "mol_rmsdtt'+option+'.dat" using 1:2 title \'Replica One\' with lines,\\\n\t""\tusing 1:3 title \'Replica Two\' with lines,\\\n\t""\tusing 1:4 title \'Replica Three\' with lines,'+
                        '\\\n\t""\tusing 1:5 title \'Replica Four\' with lines\n \nexit ')
        rmsd_graph.close()

        rmsd_cmds ="gnuplot>load 'mol_rmsdtt"+option+".p'"
        rmsd_plot=subprocess.Popen(rmsd_cmds, shell=True).wait()

#calls catdcd to make clusters
def make_clusters(option):
        for i in range(4):
                for j in range(6):
                        cat_cmds = "./catdcd/catdcd -o clusters"+option+"/cluster"+str(i)+"."+str(j)+".dcd  -f clust"+str(i)+"."+str(j)+".txt output"+option+"/"+str(i)+"/mol.job0."+str(i)+".dcd"
                        cat=subprocess.Popen(cat_cmds, shell=True).wait()

#determines RMSD of explict versus gas and gbis
def calc_rmsd():
        all_rmsd_in = open('mol_rmsd_all.tcl', 'w')
        all_rmsd_in.write('set outfile [open mol_rmsd_all.dat w]\nmol new conf/cluster0.0.pdb\nmol new conf_gas/cluster0.0.pdb\nmol new conf_gbis/cluster0.0.pdb\nfor {set i 0} {$i <=2} {incr i} {\n'+
                        ' set mol$i [atomselect $i "all"]\n}\nfor {set j 1} {$j <=2} {incr j} {\n $mol0 move [measure fit $mol0 [set mol$j]]\n puts $outfile "RMSD:  [measure rmsd $mol0 [set mol$j]]"\n}\nexit')
        all_rmsd_in.close()

        all_rmsd_cmds = "vmd -dispdev text -e mol_rmsd_all.tcl>rmsd.out"
        all_rmsd=subprocess.Popen(all_rmsd_cmds, shell=True).wait()

#moves significant documents to output folder
def make_folder(out_dir, folder_name):
        if os.path.exists(folder_name):
                shutil.rmtree(folder_name)
        os.makedirs(folder_name)
        shutil.copy("conf/cluster0.0.pdb", folder_name+"/mol_reg.pdb")
        shutil.copy("conf_gas/cluster0.0.pdb", folder_name+"/mol_gas.pdb")
        shutil.copy("conf_gbis/cluster0.0.pdb", folder_name+"/mol_gbis.pdb")
        shutil.copy("mol_rmsd_all.dat", folder_name+"/mol_rmsd_all.dat")
        
        os.chdir("../")
        with closing(tarfile.open(out_dir+".tar.gz", "w:gz")) as tar:
                tar.add(out_dir, arcname=os.path.basename(out_dir))
        shutil.rmtree(out_dir)

#initial input, checks user input file name
opts, args = getopt.getopt(sys.argv[1:], "n:i:")
for opt, arg in opts:
        if opt =='-n':
                numprocs=arg
                print(arg)
        elif opt == '-i':
                in_line=arg.split()
                in_type=in_line[0]
                instring=in_line[1]
                outfile=in_line[2]
                if os.path.exists(outfile):
                        print("Folder %s exists!")%outfile
                       #        shutil.rmtree(outfile)
                #shutil.copytree("src_files", outfile)
                os.chdir(outfile)
                print("Made directory! %s")%outfile

                #for all
                #call_babel(in_type,instring)
                #netcharge=fix_pdb()
                #call_antechamber(netcharge)
                #fix_prm()
                #call_psfgen()
                #rest_colvars()

                #regular operations
                reg_file_extension = "_wb"
                reg_option = ""
                reg_pdb_ext="ref"
                solvate_cmds()
                #make_xsc()
                #rest_vmd()
                #call_namd_exp(reg_option, numprocs)
                #calc_voltrend("-npt")
                #namd_remd(reg_option, reg_file_extension,reg_pdb_ext, numprocs)
                #sort_replicas(reg_option)
                #vmd_cluster(reg_option)
                make_clusters(reg_option)

                #GBIS operations
                gbis_file_extension = ""
                gbis_option = "_gbis"
                gbis_pdb_ext=""
                #call_namd(gbis_option, numprocs)
                #namd_remd(gbis_option, gbis_file_extension,gbis_pdb_ext, numprocs)
                #sort_replicas(gbis_option)
                #vmd_cluster(gbis_option)
                make_clusters(gbis_option)

                #gas phase operations
                gas_file_extension = ""
                gas_option = "_gas"
                gas_pdb_ext=""
                #call_namd(gas_option, numprocs)
                #namd_remd(gas_option, gas_file_extension,gas_pdb_ext, numprocs)
                #sort_replicas(gas_option)
                vmd_cluster(gas_option)
                make_clusters(gas_option)

                calc_rmsd()
                make_folder(outfile,"../"+outfile+"_out")

        else:
                print("Not an option!!")

print ("All done!")
