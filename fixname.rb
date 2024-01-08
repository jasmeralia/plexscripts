#!/usr/bin/env ruby

modelnames = IO.readlines("modelswithspaces.lst")
filestorename = IO.readlines("torename.lst")

filestorename.each do |fname|
  origfname = fname.rstrip
  # puts "Fixing up #{origfname}"
  newfname = origfname.dup
  modelnames.each do |modelnamewithspace|
    modelnamespace = modelnamewithspace.rstrip
    modelname = modelnamespace.gsub(' ', '')
    # puts "Checking for model #{modelnamespace} (#{modelname})"
    newfname.gsub!("#{modelname}_", "#{modelnamespace}, ")
    # puts "New filename: #{newfname}"
  end
  newfname.gsub!('NancyA_', 'Nancy Ace, ')
  # New filename: NancyA_Sybil_WorkingOutForSex_1920x1080.mp4
  newfname.gsub!(/_[36]0fps/, '')
  newfname.gsub!('_4096x2160', '')
  newfname.gsub!('_3840x2160', '')
  newfname.gsub!('_2048x1080', '')
  newfname.gsub!('_1920x1080', '')
  newfname.gsub!('_1280x720', '')
  newfname.gsub!('_HD1080', '')
  newfname.gsub!('_HD720', '')
  newfname.gsub!(/([a-z])([A-Z])/, '\1 \2')
  newfname.gsub!(/_/, ', ')
  newfname.gsub!(/.*\K_/, ' - ') unless newfname =~ / - /
  newfname.gsub!(/.*\K, /, ' - ') unless newfname =~ / - /
  newfname.gsub!(/([A-Z])([A-Z])/, '\1 \2')
  if newfname != origfname
    puts "Final fixed filename: #{newfname}\n"
    puts "mv \"#{origfname}\" \"#{newfname}\""
    File.rename(origfname, newfname)
  end
end
