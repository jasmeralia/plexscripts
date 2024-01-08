#!/usr/bin/env ruby

base_dir = '/home/morgan/Media/NSFW Scenes'
dir_list = Dir.entries(base_dir).select { |file| File.directory?(File.join(base_dir, file)) }
dir_list.each do |this_dir|
  this_path = File.join(base_dir, this_dir)
#   puts "Checking contents of '#{this_path}'"
  file_list = Dir.entries(this_path).select { |file| !File.directory?(File.join(this_path, file)) }
  file_list.each do |file|
    # puts "Checking file '#{file}'"
    this_file_path = File.join(this_path, file)
    if !file.downcase.start_with?(this_dir.downcase)
      puts "#{this_file_path} does not start with #{this_dir} and needs to be corrected."
    # else
    #   puts "#{this_file_path} starts with the proper name."
    end
  end
end
