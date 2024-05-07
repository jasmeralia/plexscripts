#
# Rakefile for Chef Server Repository
#
# Author:: Adam Jacob (<adam@opscode.com>)
# Copyright:: Copyright (c) 2008 Opscode, Inc.
# License:: Apache License, Version 2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# rubocop:disable Metrics/LineLength

task default: [:list]

desc 'Lists all the tasks.'
task :list do
  puts "Tasks:\n- #{Rake::Task.tasks.join("\n- ")}"
end

desc 'Test Python Linting'
task :python do
  puts 'Checking Python files...'
  sh 'pylint *.py'
  puts 'Done, no errors found.'
  puts ''
end

desc 'Python linting error summary'
task :pylint_summary do
  puts 'Aggregating summary of Pylint errors...'
  sh "pylint *.py 2>&1 | grep ':' | cut -d':' -f4- | grep ':' | sort | uniq -c | sort -n"
end

desc 'Test shell linting'
task :shellcheck do
  puts 'Checking shell scripts...'
  sh 'shellcheck *.sh'
  puts 'Done, no errors found.'
  puts ''
end

desc 'Run all linting tests'
task test: %i[python shellcheck]

desc 'Run all linting summaries'
task summary: %i[pylint_summary]
