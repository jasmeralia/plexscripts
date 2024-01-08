#!/usr/bin/env ruby

require 'pp'

DEBUG = 0
START_NAME = if ARGV[0].nil? || ARGV[0] == ''
               'TBD - '
             else
               "#{ARGV[0]} - "
             end
base_dir = '/home/morgan/Downloads'
file_list = Dir.entries(base_dir).select { |file| !File.directory?(File.join(base_dir, file)) }
file_list.each do |orig_fname|
  next unless orig_fname.end_with?(".mp4")
  next unless orig_fname.start_with?("Scene ")
  puts "Original Filename: #{orig_fname}" if DEBUG == 1
  scene_number = orig_fname.match(/Scene ([0-9]+) From .*/).captures[0]
  if scene_number.nil? || scene_number.empty?
    puts "Error: Could not find scene number in string match of '#{orig_fname}'!"
    exit 1
  end
  puts "Scene number: #{scene_number}" if DEBUG == 1
  new_fname = orig_fname.gsub(/Scene #{scene_number} From /, START_NAME)
  new_fname = new_fname.gsub(/ - 2160p/, '')
  new_fname = new_fname.gsub(/ - 1080p/, '')
  new_fname = new_fname.gsub(/ - 720p/, '')
  new_fname = new_fname.gsub(/ - 480p/, '')
  new_fname = new_fname.gsub(/ - 360p/, '')
  new_fname = new_fname.gsub(/ - Low/, '')
  new_fname = new_fname.gsub(/ Volume /, ' ')
  new_fname = new_fname.gsub(/ Vol /, ' ')
  new_fname = new_fname.gsub(/Vol([0-9]+).mp4/, '#\1.mp4')
  new_fname = new_fname.gsub(/V([0-9]+).mp4/, '#\1.mp4')
  new_fname = new_fname.gsub(/ ([0-9]+).mp4/, ' #\1.mp4')
  new_fname = new_fname.gsub(/(.*) - (.*) The.mp4/, '\1 - The \2.mp4')
  new_fname = new_fname.gsub(/.mp4/, " (Scene \##{scene_number}).mp4")
  puts "Renaming '#{orig_fname}' to '#{new_fname}'..."
  File.rename("#{base_dir}/#{orig_fname}", "#{base_dir}/#{new_fname}")
  puts "Done."
end
