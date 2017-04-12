class: CommandLineTool
cwlVersion: v1.0
$namespaces:
  cwltool: http://commonwl.org/cwltool#
requirements:
  cwltool:LoadListingRequirement:
    loadListing: shallow_listing
  InlineJavascriptRequirement: {}
inputs:
  d: Directory
outputs:
  out: stdout
stdout: output.txt
arguments:
  [echo, "${if(inputs.d.listing[0].class === 'Directory' && inputs.d.listing[0].listing === undefined) {return 'true';} else {return 'false';}}"]
